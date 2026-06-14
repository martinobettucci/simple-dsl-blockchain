"""Blockchain node: Flask RPC server + event-driven consensus.

Roles (chosen at launch): miner / validator / both / full.  The node keeps all
consensus state in a :class:`ChainState` guarded by one re-entrant lock; network
broadcasts always happen *outside* the lock.  A background worker thread does
peer discovery and (for miners) the build → PoW → propose loop; validators sign
reactively in ``/block_proposal`` and finalization happens reactively in
``/block_signature`` once quorum is reached.
"""

import argparse
import json
import logging
import threading
import time
from typing import Dict, List

from flask import Flask, request, jsonify

from .config import load_config, apply_data_dir
from . import wallet as wallet_mod
from . import dsl
from . import network
from .network import ChainStore, PeerInfo
from .transaction import Transaction
from .mempool import Mempool
from .block import Block, block_id, calc_quorum, distribute_rewards, GENESIS_HASH

log = logging.getLogger("node")


class ChainState:
    def __init__(self, cfg, wallet: Dict, local_role: str, port: int,
                 store: ChainStore, validator_set: List[str], peers: List[PeerInfo],
                 wallet_path: str = None):
        self.cfg = cfg
        self.wallet = wallet
        self.wallet_path = wallet_path
        self.local_role = local_role
        self.pubkey = wallet["public_key"]
        self.port = port
        self.store = store
        self.validator_set = validator_set
        self.quorum = calc_quorum(len(validator_set), cfg.QUORUM_PERCENT)
        self.peers = peers
        self.lock = threading.RLock()
        self.blocks: Dict[str, Block] = {}
        self.pending: Dict[str, Block] = {}
        self.pending_created_at: Dict[str, float] = {}
        self.chain: List[Block] = []
        self.tip_hash = GENESIS_HASH
        self.active_state: Dict[str, int] = {}
        self.active_balances: Dict[str, int] = {}
        self.mempool = Mempool(balances={}, mode=cfg.TX_QUEUE_MODE)
        self._bootstrap()

    # --- role helpers --- #
    @property
    def supports_mining(self) -> bool:
        return self.local_role in ("miner", "both", "full")

    @property
    def supports_validation(self) -> bool:
        return self.local_role in ("validator", "both", "full")

    @property
    def is_economic_validator(self) -> bool:
        return self.supports_validation and self.pubkey in self.validator_set

    # --- bootstrap / canonical recomputation --- #
    def _bootstrap(self) -> None:
        with self.lock:
            self.blocks = self.store.load_all_blocks()
            self.pending = self.store.load_pending()
            now = time.time()
            self.pending_created_at = {bid: now for bid in self.pending}
            self._recompute_canonical_locked()

    def _recompute_canonical_locked(self) -> None:
        self.chain = self.store.select_canonical_chain(self.blocks)
        if self.chain:
            self.tip_hash = block_id(self.chain[-1])
            self.active_state, self.active_balances = self.store.compute_active_state_and_balances(self.chain)
        else:
            self.tip_hash = GENESIS_HASH
            self.active_state, self.active_balances = {}, {}
        self.store.save_state(self.active_state)
        self.store.save_balances(self.active_balances)
        self.mempool.balances = dict(self.active_balances)
        self._sync_mempool_locked()

    def _sync_mempool_locked(self) -> None:
        """Drop confirmed txs and bump nonce floors to the on-chain maxima."""
        chain_nonces: Dict[str, int] = {}
        for b in self.chain:
            for tx in b.transactions:
                chain_nonces[tx.from_addr] = max(chain_nonces.get(tx.from_addr, 0), tx.nonce)
        self.mempool.drop_confirmed(chain_nonces)
        for addr, n in chain_nonces.items():
            self.mempool.nonces[addr] = max(self.mempool.nonces.get(addr, 0), n)

    # --- RPC-facing operations --- #
    def status(self) -> Dict:
        with self.lock:
            height = self.chain[-1].header.height if self.chain else 0
            return {
                "pubkey": self.pubkey,
                "supports_mining": self.supports_mining,
                "supports_validation": self.supports_validation,
                "height": height,
                "tip_hash": self.tip_hash,
            }

    def role_challenge(self, nonce: str) -> Dict:
        return {"pubkey": self.pubkey, "signature": wallet_mod.sign(self.wallet, nonce)}

    def submit_tx(self, tx_json: Dict) -> Dict:
        tx = Transaction.from_json(tx_json)
        tx_hash = tx.hash()
        with self.lock:
            if tx_hash in self.mempool.tx_hashes:
                return {"status": "duplicate", "tx_hash": tx_hash}
            accepted = self.mempool.add_tx(tx)
        if accepted:
            self._safe_broadcast(network.broadcast_tx, tx.to_json())
            return {"status": "accepted", "tx_hash": tx_hash}
        return {"status": "rejected", "tx_hash": tx_hash}

    def on_block_proposal(self, block_json: Dict) -> Dict:
        block = Block.from_json(block_json)
        bid = block_id(block)
        sig_payload = None
        finalized = None
        with self.lock:
            if bid in self.blocks:
                return {"status": "known"}
            block = self.pending.get(bid) or block
            if bid not in self.pending:
                if not self._validate_candidate_locked(block):
                    return {"status": "invalid"}
                self.pending[bid] = block
                self.pending_created_at[bid] = time.time()
            if self.is_economic_validator and self.pubkey not in block.validator_signatures:
                sig = wallet_mod.sign(self.wallet, block.hash())
                if block.add_validator_signature(self.pubkey, sig, self.validator_set):
                    self.store.save_pending(block)
                    sig_payload = {"block_hash": block.hash(), "val_pub": self.pubkey, "sig": sig}
            if not block.finalized and block.signer_count(self.validator_set) >= self.quorum:
                finalized = self._try_finalize_locked(block)
        if sig_payload:
            self._safe_broadcast(network.broadcast_block_signature, sig_payload)
        if finalized:
            self._safe_broadcast(network.broadcast_block_finalized, finalized.to_json())
        return {"status": "ok"}

    def on_block_signature(self, payload: Dict) -> Dict:
        bhash = payload.get("block_hash")
        val_pub = payload.get("val_pub")
        sig = payload.get("sig")
        finalized = None
        with self.lock:
            block = self.pending.get(bhash) or self.blocks.get(bhash)
            if block is None:
                return {"status": "unknown_block", "sig_count": 0}
            added = block.add_validator_signature(val_pub, sig, self.validator_set)
            count = block.signer_count(self.validator_set)
            if added:
                if block.finalized:
                    self.store.save_block(block)  # record late signature for transparency
                else:
                    self.store.save_pending(block)
                    if count >= self.quorum:
                        finalized = self._try_finalize_locked(block)
        if finalized:
            self._safe_broadcast(network.broadcast_block_finalized, finalized.to_json())
        return {"status": "ok", "sig_count": count}

    def on_block_finalized(self, block_json: Dict) -> Dict:
        block = Block.from_json(block_json)
        bid = block_id(block)
        with self.lock:
            if bid in self.blocks:
                return {"status": "known"}
            if not self._validate_finalized_locked(block):
                return {"status": "invalid"}
            self.blocks[bid] = block
            self.store.save_block(block)
            self.pending.pop(bid, None)
            self.pending_created_at.pop(bid, None)
            self.store.delete_pending(bid)
            self._recompute_canonical_locked()
            log.info("ACCEPTED finalized height=%s hash=%s", block.header.height, bid[:12])
        self._safe_broadcast(network.broadcast_block_finalized, block.to_json())
        return {"status": "ok"}

    def pending_summary(self) -> Dict:
        with self.lock:
            out = [{
                "hash": bid,
                "height": b.header.height,
                "miner": b.header.miner,
                "signatures": b.signer_count(self.validator_set),
                "quorum": self.quorum,
                "finalized": b.finalized,
            } for bid, b in self.pending.items()]
        return {"pending": out, "quorum": self.quorum}

    # --- validation --- #
    def _validate_candidate_locked(self, block: Block) -> bool:
        parent = self.blocks.get(block.header.prev_hash)
        if parent is None or block.header.height != parent.header.height + 1:
            return False
        if not block.has_valid_pow(self.cfg.DIFFICULTY_BITS):
            return False
        try:
            state = dict(parent.state)
            for tx in block.transactions:
                if not tx.verify():
                    return False
                state = dsl.execute(tx.script, state)
        except Exception:
            return False
        return state == block.state

    def _validate_finalized_locked(self, block: Block) -> bool:
        if block.is_genesis():
            return True
        parent = self.blocks.get(block.header.prev_hash)
        if parent is None or block.header.height != parent.header.height + 1:
            return False
        if not block.has_valid_pow(self.cfg.DIFFICULTY_BITS):
            return False
        try:
            state = dict(parent.state)
            for tx in block.transactions:
                if not tx.verify():
                    return False
                state = dsl.execute(tx.script, state)
        except Exception:
            return False
        if state != block.state:
            return False
        # signers_frozen must be a quorum of real validators, each with a valid signature
        frozen = block.signers_frozen
        if len(frozen) < self.quorum:
            return False
        for v in frozen:
            if v not in self.validator_set:
                return False
            s = block.validator_signatures.get(v)
            if not s or not wallet_mod.verify(v, block.hash(), s):
                return False
        # balances must equal the reward distribution to the frozen signers
        expected = distribute_rewards(block.header.miner, block.transactions, frozen, parent.balances, self.cfg)
        return expected == block.balances

    def _try_finalize_locked(self, block: Block):
        if block.finalized:
            return None
        parent = self.blocks.get(block.header.prev_hash)
        if parent is None:
            return None
        try:
            block.finalize(self.validator_set, parent.balances, self.cfg)
        except ValueError:
            return None
        bid = block_id(block)
        self.blocks[bid] = block
        self.store.save_block(block)
        self.pending.pop(bid, None)
        self.pending_created_at.pop(bid, None)
        self.store.delete_pending(bid)
        self._recompute_canonical_locked()
        log.info("FINALIZED height=%s hash=%s signers=%s",
                 block.header.height, bid[:12], [s[:8] for s in block.signers_frozen])
        return block

    # --- mining / maintenance --- #
    def expire_pending(self) -> None:
        now = time.time()
        with self.lock:
            expired = [bid for bid, t in list(self.pending_created_at.items())
                       if not self.pending[bid].finalized
                       and now - t > self.cfg.BLOCK_CANDIDATE_TTL]
            requeue: List[Transaction] = []
            for bid in expired:
                blk = self.pending.pop(bid, None)
                self.pending_created_at.pop(bid, None)
                self.store.delete_pending(bid)
                if blk and blk.header.miner == self.pubkey:
                    requeue.extend(blk.transactions)
            if requeue:
                self.mempool.requeue(requeue)

    def mine_once(self) -> None:
        self.expire_pending()
        with self.lock:
            mine_tip = self.tip_hash
            if any(b.header.prev_hash == mine_tip and b.header.miner == self.pubkey
                   for b in self.pending.values()):
                return  # already proposing on this tip
            if len(self.mempool) == 0:
                return
            txs = self.mempool.pop_for_block(self.cfg.BLOCK_TX_CAP)
            parent = self.blocks.get(mine_tip)
            height = (parent.header.height + 1) if parent else 1
            parent_state = dict(self.active_state)
            parent_balances = dict(self.active_balances)
        if not txs:
            return
        candidate = Block.create_candidate(mine_tip, height, self.pubkey, txs,
                                           parent_state, parent_balances, self.cfg)
        candidate.proof_of_work(self.cfg.DIFFICULTY_BITS)

        sig_payload = None
        finalized = None
        with self.lock:
            if self.tip_hash != mine_tip:        # tip advanced during PoW
                self.mempool.requeue(txs)
                return
            bid = block_id(candidate)
            self.pending[bid] = candidate
            self.pending_created_at[bid] = time.time()
            self.store.save_pending(candidate)
            if self.is_economic_validator:
                sig = wallet_mod.sign(self.wallet, candidate.hash())
                if candidate.add_validator_signature(self.pubkey, sig, self.validator_set):
                    sig_payload = {"block_hash": candidate.hash(), "val_pub": self.pubkey, "sig": sig}
                    if candidate.signer_count(self.validator_set) >= self.quorum:
                        finalized = self._try_finalize_locked(candidate)
            log.info("PROPOSED height=%s hash=%s txs=%s premiums=%s",
                     candidate.header.height, bid[:12], len(txs), [t.premium for t in txs])
        self._safe_broadcast(network.broadcast_block_proposal, candidate.to_json())
        if sig_payload:
            self._safe_broadcast(network.broadcast_block_signature, sig_payload)
        if finalized:
            self._safe_broadcast(network.broadcast_block_finalized, finalized.to_json())

    def _safe_broadcast(self, fn, payload) -> None:
        try:
            fn(self.peers, payload)
        except Exception:
            log.debug("broadcast failed", exc_info=True)

    def worker_loop(self) -> None:
        tick = 0
        while True:
            if tick % 5 == 0:
                try:
                    network.discover_peers(self.peers, self.validator_set)
                except Exception:
                    log.debug("discovery failed", exc_info=True)
            try:
                if self.supports_mining:
                    self.mine_once()
                else:
                    self.expire_pending()
            except Exception:
                log.exception("worker error")
            tick += 1
            time.sleep(1.0)


def create_app(state: ChainState) -> Flask:
    app = Flask(__name__)

    def _body() -> Dict:
        return request.get_json(force=True, silent=True) or {}

    @app.get("/status")
    def status():
        return jsonify(state.status())

    @app.post("/role_challenge")
    def role_challenge():
        return jsonify(state.role_challenge(_body().get("nonce", "")))

    @app.post("/tx")
    def tx():
        return jsonify(state.submit_tx(_body()))

    @app.post("/block_proposal")
    def block_proposal():
        return jsonify(state.on_block_proposal(_body()))

    @app.post("/block_signature")
    def block_signature():
        return jsonify(state.on_block_signature(_body()))

    @app.post("/block_finalized")
    def block_finalized():
        return jsonify(state.on_block_finalized(_body()))

    @app.get("/pending")
    def pending():
        return jsonify(state.pending_summary())

    @app.errorhandler(Exception)
    def _on_error(e):  # malformed input must not crash a worker thread
        log.debug("request error", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 400

    return app


def build_state_from_args(args) -> ChainState:
    cfg = load_config(args.config)
    apply_data_dir(cfg, args.data_dir)
    w = wallet_mod.load_wallet(args.wallet)
    with open(args.validators) as f:
        validator_set = [v["pubkey"] for v in json.load(f).get("validators", [])]
    peers = network.load_peers(args.peers, self_port=args.port)
    store = ChainStore(cfg.BLOCKS_DIR, cfg.PENDING_DIR, cfg.STATE_FILE, cfg.BAL_FILE)
    return ChainState(cfg, w, args.local_role, args.port, store, validator_set, peers,
                      wallet_path=args.wallet)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pedagogical blockchain node")
    parser.add_argument("--config", required=True)
    parser.add_argument("--local-role", choices=["miner", "validator", "both", "full"], required=True)
    parser.add_argument("--wallet", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--peers", required=True)
    parser.add_argument("--validators", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    state = build_state_from_args(args)
    app = create_app(state)

    threading.Thread(target=state.worker_loop, daemon=True).start()
    log.info("node %s role=%s port=%s peers=%d validators=%d quorum=%d",
             state.pubkey[:12], args.local_role, args.port, len(state.peers),
             len(state.validator_set), state.quorum)
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
