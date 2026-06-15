"""Blockchain node: Flask RPC server + event-driven consensus + mesh sync.

Roles (chosen at launch): miner / validator / both / full / archive.  The node
keeps all consensus state in a :class:`ChainState` guarded by one re-entrant
lock; network broadcasts always happen *outside* the lock.

Nothing about the protocol is hard-coded except the genesis block (created by the
archive from a spec).  The active validator set and protocol config are *derived*
from the chain by folding governance transactions (see ``governance.py``): the
governance snapshot produced by block ``h-1`` governs block ``h`` (who may sign
it, the quorum, the PoW difficulty and the active config).

An ``archive`` node has no wallet: it creates the genesis, passively stores every
finalized block and serves sync to peers.  Other nodes start with only a wallet
and a single ``--bootstrap`` endpoint; they resolve the archive (directly or by
referral), sync the chain, and then discover the rest of the mesh by gossip.
"""

import argparse
import hashlib
import json
import logging
import threading
import time
from typing import Dict, List, Optional

from flask import Flask, request, jsonify

from .config import load_config, apply_data_dir, effective_config
from . import wallet as wallet_mod
from . import dsl
from . import network
from .network import ChainStore, PeerInfo
from .transaction import Transaction
from .mempool import Mempool
from .block import Block, BlockHeader, block_id, distribute_rewards, GENESIS_HASH
from .governance import GovernanceState, apply_block, quorum_at, genesis_state

log = logging.getLogger("node")


def build_genesis_from_spec(spec: Dict) -> Block:
    """Build the genesis block from a bootstrap spec (archive-only).

    ``spec`` embeds the only common hard-coded data: the initial validator set,
    the bootstrap governable config, and the initial balances/state.
    """
    validators = sorted(v["pubkey"] for v in spec.get("validators", []))
    g0 = GovernanceState(
        validators=validators,
        config=dict(spec.get("config", {})),
        miss_counts={v: 0 for v in validators},
        last_signed_height={v: 0 for v in validators},
    )
    header = BlockHeader(prev_hash=GENESIS_HASH, height=0, nonce=0, timestamp=0, miner="genesis")
    return Block(header=header, transactions=[], state=dict(spec.get("state", {})),
                 balances=dict(spec.get("balances", {})), finalized=True,
                 signers_frozen=[], governance=g0.to_snapshot())


class ChainState:
    def __init__(self, cfg, wallet: Optional[Dict], local_role: str, port: int,
                 store: ChainStore, peers: List[PeerInfo],
                 archive_addr: Optional[str] = None, wallet_path: str = None):
        self.cfg = cfg
        self.wallet = wallet
        self.wallet_path = wallet_path
        self.local_role = local_role
        self.pubkey = wallet["public_key"] if wallet else None
        self.port = port
        self.store = store
        self.peers = peers
        self.archive_addr = archive_addr
        self.lock = threading.RLock()
        self.blocks: Dict[str, Block] = {}
        self.pending: Dict[str, Block] = {}
        self.pending_created_at: Dict[str, float] = {}
        self.chain: List[Block] = []
        self.tip_hash = GENESIS_HASH
        self.active_state: Dict[str, int] = {}
        self.active_balances: Dict[str, int] = {}
        self._gov_cache: Dict[str, GovernanceState] = {}
        self.mempool = Mempool(balances={}, mode=cfg.TX_QUEUE_MODE)
        self._bootstrap()

    # --- role helpers --- #
    @property
    def is_archive(self) -> bool:
        return self.local_role == "archive"

    @property
    def supports_mining(self) -> bool:
        return self.local_role in ("miner", "both", "full")

    @property
    def supports_validation(self) -> bool:
        return self.local_role in ("validator", "both", "full")

    def _is_validator_in(self, gs: Optional[GovernanceState]) -> bool:
        return self.supports_validation and self.pubkey is not None and gs is not None \
            and self.pubkey in gs.validators

    # --- governance derivation (per-ancestry, memoized) --- #
    def _gov_produced_by_locked(self, bid: str) -> Optional[GovernanceState]:
        """G_h: the governance snapshot produced *by* block ``bid`` (governs its
        children).  Folded along the block's own ancestry, so forks each get
        their own state.  Returns ``None`` if an ancestor is missing."""
        if bid in self._gov_cache:
            return self._gov_cache[bid]
        stack: List[Block] = []
        cur = bid
        while cur not in self._gov_cache:
            blk = self.blocks.get(cur)
            if blk is None:
                return None
            if blk.is_genesis():
                self._gov_cache[cur] = genesis_state(blk)
                break
            stack.append(blk)
            cur = blk.header.prev_hash
        for blk in reversed(stack):
            parent_gs = self._gov_cache[blk.header.prev_hash]
            self._gov_cache[block_id(blk)] = apply_block(parent_gs, blk, height=blk.header.height)
        return self._gov_cache.get(bid)

    def _current_gov_locked(self) -> Optional[GovernanceState]:
        return self._gov_produced_by_locked(self.tip_hash)

    def _parent_gov_locked(self, block: Block) -> Optional[GovernanceState]:
        return self._gov_produced_by_locked(block.header.prev_hash)

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

    def _genesis_fingerprint_locked(self) -> Optional[str]:
        g = self.blocks.get(GENESIS_HASH)
        if not g:
            return None
        payload = json.dumps({"governance": g.governance, "state": g.state, "balances": g.balances},
                             sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]

    # --- RPC-facing operations --- #
    def status(self) -> Dict:
        with self.lock:
            height = self.chain[-1].header.height if self.chain else 0
            return {
                "pubkey": self.pubkey,
                "role": self.local_role,
                "is_archive": self.is_archive,
                "archive_addr": self.archive_addr,
                "supports_mining": self.supports_mining,
                "supports_validation": self.supports_validation,
                "height": height,
                "tip_hash": self.tip_hash,
                "genesis_fingerprint": self._genesis_fingerprint_locked(),
            }

    def role_challenge(self, nonce: str) -> Dict:
        if not self.wallet:
            return {"pubkey": None, "signature": ""}
        return {"pubkey": self.pubkey, "signature": wallet_mod.sign(self.wallet, nonce)}

    def peers_summary(self) -> Dict:
        with self.lock:
            return {"peers": [p.to_dict() for p in self.peers]}

    def announce_peer(self, host: str, port: int) -> Dict:
        with self.lock:
            self.peers = network.merge_peers(self.peers, [{"host": host, "port": port}],
                                             self_port=self.port)
        return {"status": "ok"}

    def genesis_json(self) -> Dict:
        with self.lock:
            g = self.blocks.get(GENESIS_HASH)
            return {"block": g.to_json() if g else None}

    def blocks_since(self, since: int, limit: int) -> Dict:
        with self.lock:
            out = [b.to_json() for b in self.chain if b.header.height > since][:limit]
        return {"blocks": out}

    def governance_summary(self) -> Dict:
        with self.lock:
            gp = self._current_gov_locked()
            return gp.to_snapshot() if gp else {
                "validators": [], "quorum": 0, "config": {},
                "applications": {}, "config_proposals": {},
                "miss_counts": {}, "last_signed_height": {},
            }

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
            gp = self._parent_gov_locked(block)
            if gp is not None and self._is_validator_in(gp) and self.pubkey not in block.validator_signatures:
                sig = wallet_mod.sign(self.wallet, block.hash())
                if block.add_validator_signature(self.pubkey, sig, gp.validators):
                    self.store.save_pending(block)
                    sig_payload = {"block_hash": block.hash(), "val_pub": self.pubkey, "sig": sig}
            if self._should_finalize_locked(block, gp):
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
        count = 0
        with self.lock:
            block = self.pending.get(bhash) or self.blocks.get(bhash)
            if block is None:
                return {"status": "unknown_block", "sig_count": 0}
            gp = self._parent_gov_locked(block)
            if gp is None:
                return {"status": "unknown_parent", "sig_count": 0}
            added = block.add_validator_signature(val_pub, sig, gp.validators)
            count = block.signer_count(gp.validators)
            if added:
                if block.finalized:
                    self.store.save_block(block)  # record late signature for transparency
                else:
                    self.store.save_pending(block)
                    if self._should_finalize_locked(block, gp):
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
            out = []
            current_q = 0
            cg = self._current_gov_locked()
            if cg is not None:
                current_q = quorum_at(cg)
            for bid, b in self.pending.items():
                gp = self._parent_gov_locked(b)
                out.append({
                    "hash": bid,
                    "height": b.header.height,
                    "miner": b.header.miner,
                    "signatures": b.signer_count(gp.validators) if gp else len(b.validator_signatures),
                    "quorum": quorum_at(gp) if gp else 0,
                    "finalized": b.finalized,
                })
        return {"pending": out, "quorum": current_q}

    def _should_finalize_locked(self, block: Block, gp: Optional[GovernanceState]) -> bool:
        """Whether *this* node may finalize ``block`` now.

        The block's proposer is the sole finalizer, so ``signers_frozen`` has a
        single decider and is deterministic across the mesh (it is excluded from
        the identity hash, so divergent signer sets could not otherwise be
        reconciled).  The proposer freezes signers once *all* current validators
        have signed, or after ``SIGNATURE_GRACE`` seconds with at least a quorum
        — so validators that are online but beyond the bare quorum are still
        credited and do not accrue spurious missed-quorum counts.
        """
        if gp is None or block.finalized:
            return False
        if block.header.miner != self.pubkey:   # only the proposer finalizes
            return False
        n = block.signer_count(gp.validators)
        if n < quorum_at(gp):
            return False
        if n >= len(gp.validators):              # everyone signed -> no need to wait
            return True
        age = time.time() - self.pending_created_at.get(block_id(block), time.time())
        return age >= self.cfg.SIGNATURE_GRACE

    def finalize_ready(self) -> None:
        """Finalize the proposer's own blocks whose grace window has elapsed.

        Needed because, when a validator is offline, no further signature arrives
        to drive finalization through :meth:`on_block_signature` — the timeout
        path lives here in the worker loop instead."""
        finalized = []
        with self.lock:
            for bid in list(self.pending.keys()):
                b = self.pending.get(bid)
                gp = self._parent_gov_locked(b) if b else None
                if b is not None and self._should_finalize_locked(b, gp):
                    fb = self._try_finalize_locked(b)
                    if fb:
                        finalized.append(fb)
        for fb in finalized:
            self._safe_broadcast(network.broadcast_block_finalized, fb.to_json())

    # --- validation --- #
    def _validate_candidate_locked(self, block: Block) -> bool:
        parent = self.blocks.get(block.header.prev_hash)
        if parent is None or block.header.height != parent.header.height + 1:
            return False
        gp = self._gov_produced_by_locked(block.header.prev_hash)
        if gp is None:
            return False
        eff = effective_config(self.cfg, gp.config)
        if not block.has_valid_pow(eff.DIFFICULTY_BITS):
            return False
        try:
            state = dict(parent.state)
            for tx in block.transactions:
                if not tx.verify():
                    return False
                if tx.type == "dsl":
                    state = dsl.execute(tx.script, state)
        except Exception:
            return False
        return state == block.state

    def _validate_finalized_locked(self, block: Block) -> bool:
        if block.is_genesis():
            gov = block.governance
            return bool(gov.get("validators")) and "QUORUM_PERCENT" in gov.get("config", {})
        parent = self.blocks.get(block.header.prev_hash)
        if parent is None or block.header.height != parent.header.height + 1:
            return False
        gp = self._gov_produced_by_locked(block.header.prev_hash)
        if gp is None:
            return False
        eff = effective_config(self.cfg, gp.config)
        if not block.has_valid_pow(eff.DIFFICULTY_BITS):
            return False
        try:
            state = dict(parent.state)
            for tx in block.transactions:
                if not tx.verify():
                    return False
                if tx.type == "dsl":
                    state = dsl.execute(tx.script, state)
        except Exception:
            return False
        if state != block.state:
            return False
        # signers_frozen must be a quorum of the parent's validators with valid signatures
        frozen = block.signers_frozen
        if len(frozen) < quorum_at(gp):
            return False
        for v in frozen:
            if v not in gp.validators:
                return False
            s = block.validator_signatures.get(v)
            if not s or not wallet_mod.verify(v, block.hash(), s):
                return False
        # balances must equal the reward distribution to the frozen signers
        if distribute_rewards(block.header.miner, block.transactions, frozen, parent.balances, eff) != block.balances:
            return False
        # governance snapshot must equal the deterministic fold of the parent state
        return apply_block(gp, block, height=block.header.height).to_snapshot() == block.governance

    def _try_finalize_locked(self, block: Block):
        if block.finalized:
            return None
        parent = self.blocks.get(block.header.prev_hash)
        if parent is None:
            return None
        gp = self._gov_produced_by_locked(block.header.prev_hash)
        if gp is None:
            return None
        eff = effective_config(self.cfg, gp.config)
        try:
            block.finalize(gp.validators, parent.balances, eff)
        except ValueError:
            return None
        # signers are now frozen -> derive and attach this block's governance snapshot
        block.governance = apply_block(gp, block, height=block.header.height).to_snapshot()
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
            gp = self._gov_produced_by_locked(mine_tip)
            if gp is None:                       # no genesis yet / not synced
                return
            eff = effective_config(self.cfg, gp.config)
            if any(b.header.prev_hash == mine_tip and b.header.miner == self.pubkey
                   for b in self.pending.values()):
                return  # already proposing on this tip
            if len(self.mempool) == 0:
                return
            # Don't propose into the void: if we can't reach quorum on our own,
            # wait until the mesh has revealed at least one validator peer.
            own = 1 if self._is_validator_in(gp) else 0
            if own < quorum_at(gp) and not any(p.is_validator for p in self.peers):
                return
            txs = self.mempool.pop_for_block(eff.BLOCK_TX_CAP)
            parent = self.blocks.get(mine_tip)
            height = (parent.header.height + 1) if parent else 1
            parent_state = dict(self.active_state)
            parent_balances = dict(self.active_balances)
        if not txs:
            return
        candidate = Block.create_candidate(mine_tip, height, self.pubkey, txs,
                                           parent_state, parent_balances, eff)
        candidate.proof_of_work(eff.DIFFICULTY_BITS)

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
            if self._is_validator_in(gp):
                sig = wallet_mod.sign(self.wallet, candidate.hash())
                if candidate.add_validator_signature(self.pubkey, sig, gp.validators):
                    sig_payload = {"block_hash": candidate.hash(), "val_pub": self.pubkey, "sig": sig}
                    if self._should_finalize_locked(candidate, gp):
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

    # --- sync + mesh --- #
    def sync_from(self, archive_url: str) -> bool:
        """Pull the chain from ``archive_url`` through the normal validation path.

        Genesis is installed first (a node has none until it syncs), then blocks
        are paged in height order and fed to :meth:`on_block_finalized`, so a
        malicious source cannot inject an invalid or governance-inconsistent block.
        """
        try:
            with self.lock:
                have_genesis = GENESIS_HASH in self.blocks
            if not have_genesis:
                g = network.fetch_genesis(archive_url)
                if g:
                    self.on_block_finalized(g)
            while True:
                with self.lock:
                    local_h = self.chain[-1].header.height if self.chain else -1
                batch = network.fetch_blocks_since(archive_url, local_h, limit=200)
                if not batch:
                    break
                for bjson in batch:
                    self.on_block_finalized(bjson)
                with self.lock:
                    new_h = self.chain[-1].header.height if self.chain else -1
                if new_h <= local_h:
                    break
            return True
        except Exception:
            log.debug("sync from %s failed", archive_url, exc_info=True)
            return False

    def discover_and_gossip(self) -> None:
        with self.lock:
            gp = self._current_gov_locked()
            vset = list(gp.validators) if gp else []
            peers_snapshot = list(self.peers)
        try:
            network.discover_peers(peers_snapshot, vset)
        except Exception:
            log.debug("discovery failed", exc_info=True)
        learned: List[Dict] = []
        for p in peers_snapshot:
            try:
                network.announce(p.url, "127.0.0.1", self.port)
            except Exception:
                pass
            try:
                learned.extend(network.fetch_peers(p.url))
            except Exception:
                continue
        if learned:
            with self.lock:
                self.peers = network.merge_peers(self.peers, learned, self_port=self.port)

    def _periodic_sync(self) -> None:
        """Catch up from the linked archive, or from the most advanced peer.

        Gossip/broadcast is best-effort, so a node (including the archive, which
        has no archive link) also pulls finalized blocks from any peer reporting
        a greater height — every node serves ``/blocks`` and ``/genesis``."""
        with self.lock:
            local_h = self.chain[-1].header.height if self.chain else -1
            peer_urls = [p.url for p in self.peers]
        targets = ([self.archive_addr] if self.archive_addr else []) + peer_urls
        for url in targets:
            if not url:
                continue
            try:
                if network.fetch_status(url).get("height", -1) > local_h:
                    self.sync_from(url)
                    return
            except Exception:
                continue

    def worker_loop(self) -> None:
        tick = 0
        while True:
            if tick % 5 == 0:
                self.discover_and_gossip()
            if tick % 7 == 0:
                self._periodic_sync()
            try:
                if self.supports_mining:
                    self.finalize_ready()   # close grace windows on our own proposals
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

    @app.get("/peers")
    def peers():
        return jsonify(state.peers_summary())

    @app.post("/announce")
    def announce():
        body = _body()
        return jsonify(state.announce_peer(body.get("host", "127.0.0.1"), int(body.get("port", 0))))

    @app.get("/genesis")
    def genesis():
        return jsonify(state.genesis_json())

    @app.get("/blocks")
    def blocks():
        since = int(request.args.get("since", -1))
        limit = int(request.args.get("limit", 200))
        return jsonify(state.blocks_since(since, limit))

    @app.get("/governance")
    def governance():
        return jsonify(state.governance_summary())

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


def _resolve_and_sync(state: ChainState, bootstrap: str) -> Optional[str]:
    """Resolve the archive (directly or by referral) and pull the chain."""
    archive = None
    for attempt in range(5):
        try:
            st = network.fetch_status(bootstrap)
            archive = bootstrap if st.get("is_archive") else st.get("archive_addr")
            if archive:
                break
        except Exception:
            log.debug("bootstrap status attempt %s failed", attempt, exc_info=True)
        time.sleep(min(2 ** attempt, 8))
    if not archive:
        log.warning("could not resolve archive from bootstrap %s", bootstrap)
        return None
    archive = network.base_url(archive)
    state.archive_addr = archive
    with state.lock:
        ep = network.parse_endpoint(archive)
        state.peers = network.merge_peers(state.peers, [{"host": ep.host, "port": ep.port}],
                                          self_port=state.port)
    network.announce(archive, "127.0.0.1", state.port)
    state.sync_from(archive)
    return archive


def build_state_from_args(args) -> ChainState:
    cfg = load_config(args.config)
    apply_data_dir(cfg, args.data_dir)
    role = args.local_role
    store = ChainStore(cfg.BLOCKS_DIR, cfg.PENDING_DIR, cfg.STATE_FILE, cfg.BAL_FILE)

    wallet = None
    if role != "archive":
        if not args.wallet:
            raise SystemExit("--wallet is required for non-archive nodes")
        wallet = wallet_mod.load_wallet(args.wallet)

    if role == "archive" and GENESIS_HASH not in store.load_all_blocks():
        if not args.genesis_spec:
            raise SystemExit("archive requires --genesis-spec to create the genesis block")
        with open(args.genesis_spec) as f:
            store.save_block(build_genesis_from_spec(json.load(f)))

    peers: List[PeerInfo] = []
    if args.bootstrap:
        peers.append(network.parse_endpoint(args.bootstrap))

    state = ChainState(cfg, wallet, role, args.port, store, peers, wallet_path=args.wallet)

    if role != "archive" and args.bootstrap:
        _resolve_and_sync(state, args.bootstrap)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Pedagogical blockchain node")
    parser.add_argument("--config", required=True)
    parser.add_argument("--local-role",
                        choices=["miner", "validator", "both", "full", "archive"], required=True)
    parser.add_argument("--wallet", help="wallet file (required unless role=archive)")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--bootstrap", help="bootstrap endpoint host:port (non-archive nodes)")
    parser.add_argument("--genesis-spec", help="genesis bootstrap spec (archive only)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    state = build_state_from_args(args)
    app = create_app(state)

    threading.Thread(target=state.worker_loop, daemon=True).start()
    with state.lock:
        gp = state._current_gov_locked()
    log.info("node %s role=%s port=%s peers=%d validators=%s archive=%s",
             (state.pubkey or "archive")[:12], args.local_role, args.port, len(state.peers),
             len(gp.validators) if gp else 0, state.archive_addr)
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
