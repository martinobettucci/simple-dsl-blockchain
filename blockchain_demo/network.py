"""Networking: peer discovery (challenge-signature), broadcasts, and the
file-based chain store with fork selection.

``ChainStore`` is pure disk + graph logic (no HTTP) so it stays unit-testable
offline.  The broadcast helpers are best-effort: a single unreachable peer must
never break a broadcast loop (§7.6), and they are meant to be called *outside*
the node's state lock.
"""

import os
import json
import time
from typing import Dict, List, Optional

import requests

from .wallet import verify
from .block import Block, block_id, GENESIS_HASH
from . import dsl


# --------------------------------------------------------------------------- #
# Peers & discovery
# --------------------------------------------------------------------------- #
class PeerInfo:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.pubkey: Optional[str] = None
        self.is_validator = False
        self.last_seen = 0.0
        self.latency_ms = 0.0

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_dict(self) -> Dict:
        return {
            "host": self.host,
            "port": self.port,
            "pubkey": self.pubkey,
            "is_validator": self.is_validator,
            "last_seen": self.last_seen,
            "latency_ms": round(self.latency_ms, 2),
        }


def _get(peer: PeerInfo, path: str, timeout: float = 2.0):
    return requests.get(peer.url + path, timeout=timeout)


def _post(peer: PeerInfo, path: str, body: Dict, timeout: float = 2.0):
    return requests.post(peer.url + path, json=body, timeout=timeout)


def load_peers(path: str, self_port: Optional[int] = None) -> List[PeerInfo]:
    """Load bootstrap endpoints from ``peers.json`` (excluding self by port)."""
    with open(path) as f:
        data = json.load(f)
    peers = []
    for p in data.get("peers", []):
        if self_port is not None and int(p["port"]) == int(self_port):
            continue
        peers.append(PeerInfo(p["host"], int(p["port"])))
    return peers


def parse_endpoint(addr: str) -> PeerInfo:
    """Parse a ``host:port`` (or full URL) string into a :class:`PeerInfo`."""
    cleaned = addr.replace("http://", "").replace("https://", "").strip("/")
    host, port = cleaned.rsplit(":", 1)
    return PeerInfo(host, int(port))


def base_url(addr: str) -> str:
    if addr.startswith("http"):
        return addr.rstrip("/")
    return "http://" + addr.rstrip("/")


def fetch_status(addr: str, timeout: float = 2.0) -> Dict:
    return requests.get(base_url(addr) + "/status", timeout=timeout).json()


def fetch_genesis(addr: str, timeout: float = 4.0) -> Optional[Dict]:
    r = requests.get(base_url(addr) + "/genesis", timeout=timeout)
    if r.status_code != 200:
        return None
    return r.json().get("block")


def fetch_blocks_since(addr: str, since: int, limit: int = 200, timeout: float = 8.0) -> List[Dict]:
    r = requests.get(base_url(addr) + "/blocks",
                     params={"since": since, "limit": limit}, timeout=timeout)
    return r.json().get("blocks", [])


def fetch_peers(addr: str, timeout: float = 2.0) -> List[Dict]:
    r = requests.get(base_url(addr) + "/peers", timeout=timeout)
    return r.json().get("peers", [])


def announce(addr: str, host: str, port: int, timeout: float = 2.0) -> bool:
    """Announce our endpoint to a peer so the mesh can learn about us."""
    try:
        requests.post(base_url(addr) + "/announce", json={"host": host, "port": port}, timeout=timeout)
        return True
    except Exception:
        return False


def merge_peers(local: List[PeerInfo], remote: List[Dict],
                self_port: Optional[int] = None, cap: int = 50) -> List[PeerInfo]:
    """Union ``local`` with the ``remote`` peer dicts, excluding self, capped."""
    by_key = {(p.host, p.port): p for p in local}
    for rp in remote:
        try:
            host, port = rp["host"], int(rp["port"])
        except (KeyError, TypeError, ValueError):
            continue
        if self_port is not None and port == int(self_port):
            continue  # localhost demo: identify self by port
        by_key.setdefault((host, port), PeerInfo(host, port))
    return list(by_key.values())[:cap]


def probe_peer(peer: PeerInfo, validator_set: List[str]) -> bool:
    """Handshake + challenge-signature (§7.2/§7.3).

    Marks ``is_validator`` only if the peer proves control of a key listed in
    ``validator_set`` by signing a fresh random nonce.  Returns reachability.
    """
    start = time.time()
    try:
        status = _get(peer, "/status").json()
    except Exception:
        return False
    peer.latency_ms = (time.time() - start) * 1000
    pubkey_claim = status.get("pubkey")
    nonce = os.urandom(32).hex()
    try:
        resp = _post(peer, "/role_challenge", {"nonce": nonce, "expect_validator": True}).json()
    except Exception:
        return False
    pubkey = resp.get("pubkey", pubkey_claim)
    sig = resp.get("signature")
    peer.pubkey = pubkey
    peer.is_validator = bool(sig and verify(pubkey, nonce, sig) and pubkey in validator_set)
    peer.last_seen = time.time()
    return True


def discover_peers(peers: List[PeerInfo], validator_set: List[str]) -> List[PeerInfo]:
    for peer in peers:
        try:
            probe_peer(peer, validator_set)
        except Exception:
            continue
    return peers


# --------------------------------------------------------------------------- #
# Broadcast clients (best-effort, call outside the state lock)
# --------------------------------------------------------------------------- #
def _broadcast(peers: List[PeerInfo], path: str, body: Dict) -> int:
    sent = 0
    for peer in peers:
        try:
            _post(peer, path, body)
            sent += 1
        except Exception:
            continue
    return sent


def broadcast_tx(peers: List[PeerInfo], tx_json: Dict) -> int:
    return _broadcast(peers, "/tx", tx_json)


def broadcast_block_proposal(peers: List[PeerInfo], block_json: Dict) -> int:
    # Send to every peer: each node self-filters (only validators in the parent
    # governance snapshot sign).  Broadcasting to all — rather than only to
    # already-discovered validators — ensures a validator that the miner has not
    # probed yet still receives the proposal, so it can sign and earn its share
    # instead of unfairly accruing missed-quorum counts while the mesh forms.
    return _broadcast(peers, "/block_proposal", block_json)


def broadcast_block_signature(peers: List[PeerInfo], payload: Dict) -> int:
    return _broadcast(peers, "/block_signature", payload)


def broadcast_block_finalized(peers: List[PeerInfo], block_json: Dict) -> int:
    return _broadcast(peers, "/block_finalized", block_json)


# --------------------------------------------------------------------------- #
# Chain store (disk + fork graph)
# --------------------------------------------------------------------------- #
class ChainStore:
    def __init__(self, blocks_dir: str, pending_dir: str, state_file: str, bal_file: str):
        self.blocks_dir = blocks_dir
        self.pending_dir = pending_dir
        self.state_file = state_file
        self.bal_file = bal_file

    @staticmethod
    def _write(path: str, obj: Dict) -> None:
        # atomic write so a concurrent reader (e.g. the explorer) never sees a
        # half-written file
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
        os.replace(tmp, path)

    @staticmethod
    def load_block(path: str) -> Block:
        with open(path) as f:
            return Block.from_json(json.load(f))

    def _store(self, directory: str, block: Block) -> str:
        bid = block_id(block)
        data = block.to_json()
        data["hash"] = bid  # genesis keeps the literal zero hash
        os.makedirs(directory, exist_ok=True)
        self._write(os.path.join(directory, f"{bid}.json"), data)
        return bid

    def save_block(self, block: Block) -> str:
        return self._store(self.blocks_dir, block)

    def save_pending(self, block: Block) -> str:
        return self._store(self.pending_dir, block)

    def _load_dir(self, directory: str) -> Dict[str, Block]:
        blocks: Dict[str, Block] = {}
        if not os.path.isdir(directory):
            return blocks
        for name in sorted(os.listdir(directory)):
            if name.endswith(".json"):
                b = self.load_block(os.path.join(directory, name))
                blocks[block_id(b)] = b
        return blocks

    def load_all_blocks(self) -> Dict[str, Block]:
        return self._load_dir(self.blocks_dir)

    def load_pending(self) -> Dict[str, Block]:
        return self._load_dir(self.pending_dir)

    def delete_pending(self, bid: str) -> None:
        path = os.path.join(self.pending_dir, f"{bid}.json")
        if os.path.exists(path):
            os.remove(path)

    def load_state(self) -> Dict[str, int]:
        if os.path.exists(self.state_file):
            with open(self.state_file) as f:
                return json.load(f).get("state", {})
        return {}

    def save_state(self, state: Dict[str, int]) -> None:
        self._write(self.state_file, {"state": state})

    def load_balances(self) -> Dict[str, int]:
        if os.path.exists(self.bal_file):
            with open(self.bal_file) as f:
                return json.load(f).get("balances", {})
        return {}

    def save_balances(self, balances: Dict[str, int]) -> None:
        self._write(self.bal_file, {"balances": balances})

    # --- fork graph & canonical selection (§5.9 / §14) --- #
    @staticmethod
    def build_fork_graph(blocks: Dict[str, Block]) -> Dict[str, List[str]]:
        graph: Dict[str, List[str]] = {}
        for bid, b in blocks.items():
            if bid == b.header.prev_hash:
                continue  # genesis is its own parent (root sentinel) — skip self-loop
            graph.setdefault(b.header.prev_hash, []).append(bid)
        return graph

    @staticmethod
    def total_pow(block: Block) -> int:
        if block.is_genesis():
            return 0
        return (1 << 256) - int(block.hash(), 16)

    @staticmethod
    def _chain_to(bid: str, blocks: Dict[str, Block]) -> Optional[List[Block]]:
        chain: List[Block] = []
        cur, seen = bid, set()
        while cur in blocks and cur not in seen:
            seen.add(cur)
            b = blocks[cur]
            chain.append(b)
            if b.is_genesis():
                chain.reverse()
                return chain
            cur = b.header.prev_hash
        return None  # orphan (missing parent) or cycle

    def select_canonical_chain(self, blocks: Dict[str, Block]) -> List[Block]:
        candidates = []
        for bid in blocks:
            chain = self._chain_to(bid, blocks)
            if chain:
                candidates.append((bid, chain, sum(self.total_pow(b) for b in chain)))
        if not candidates:
            return []

        def better(a, b) -> bool:
            (abid, achain, apow), (bbid, bchain, bpow) = a, b
            if len(achain) != len(bchain):       # longest-finalized-chain wins
                return len(achain) > len(bchain)
            if apow != bpow:                     # tie-break 1: total PoW
                return apow > bpow
            if abid != bbid:                     # tie-break 2: smallest hash
                return abid < bbid
            return achain[-1].header.timestamp < bchain[-1].header.timestamp

        best = candidates[0]
        for c in candidates[1:]:
            if better(c, best):
                best = c
        return best[1]

    def compute_active_state_and_balances(self, chain: List[Block]):
        if not chain:
            return {}, {}
        tip = chain[-1]
        return dict(tip.state), dict(tip.balances)

    @staticmethod
    def verify_chain(chain: List[Block], cfg) -> bool:
        """Structural integrity: rooted at genesis, prev-hash links, PoW, DSL
        replay, and (when present) governance snapshot consistency."""
        if not chain:
            return True
        if not chain[0].is_genesis():
            return False
        from .governance import genesis_state, apply_block
        from .config import effective_config
        state = dict(chain[0].state)
        gov = genesis_state(chain[0])
        prev = chain[0]
        for b in chain[1:]:
            if b.header.prev_hash != block_id(prev):
                return False
            eff = effective_config(cfg, gov.config)
            if not b.has_valid_pow(eff.DIFFICULTY_BITS):
                return False
            for tx in b.transactions:
                if tx.type == "dsl":  # governance txs do not mutate state
                    state = dsl.execute(tx.script, state)
            if state != b.state:
                return False
            gov = apply_block(gov, b, height=b.header.height)
            if b.governance and gov.to_snapshot() != b.governance:
                return False
            prev = b
        return True
