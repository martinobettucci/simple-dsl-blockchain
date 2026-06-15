"""Mempool: admission and ordering of pending transactions.

Admission (§5.3): valid ECDSA signature, monotonic per-address nonce, premium
>= MIN_PREMIUM, sufficient balance for the *cumulative* premium of all pending
transactions from that sender, parseable DSL, and no duplicate hash.

Ordering (§5.2): "premium" mode sorts by premium descending then arrival order
(stable, anti-censorship); "fifo" mode keeps arrival order.  Premiums are only
debited at block finalization (§5.3), so the balance check here is a soft gate
that reserves funds while transactions wait, releasing them when popped.
"""

from typing import Dict, List, Optional, Set, Tuple

from . import dsl
from . import config
from .transaction import Transaction

# Governance transaction types and their required ``data`` schema (validated here
# as a soft gate; authoritative resolution happens in ``governance.apply_block``).
_GOV_SCHEMA = {
    "validator_apply": (),
    "validator_vote": ("candidate",),
    "config_propose": ("changes",),
    "config_vote": ("pid",),
}


def _valid_governance_data(tx: Transaction) -> bool:
    if tx.type not in _GOV_SCHEMA:
        return False
    for key in _GOV_SCHEMA[tx.type]:
        if key not in tx.data:
            return False
    if tx.type == "validator_vote" and not isinstance(tx.data.get("candidate"), str):
        return False
    if tx.type == "config_propose" and not isinstance(tx.data.get("changes"), dict):
        return False
    if tx.type == "config_vote" and not isinstance(tx.data.get("pid"), str):
        return False
    return True


class Mempool:
    def __init__(self, balances: Optional[Dict[str, int]] = None, mode: Optional[str] = None):
        self.mode = mode or config.CFG.TX_QUEUE_MODE
        self._seq = 0
        self.txs: List[Tuple[int, Transaction]] = []
        self.tx_hashes: Set[str] = set()
        self.nonces: Dict[str, int] = {}
        self.reserved: Dict[str, int] = {}
        self.balances: Dict[str, int] = dict(balances or {})

    def _reorder(self) -> None:
        if self.mode == "premium":
            self.txs.sort(key=lambda item: (-item[1].premium, item[0]))
        else:  # fifo
            self.txs.sort(key=lambda item: item[0])

    def add_tx(self, tx: Transaction) -> bool:
        if tx.premium < config.CFG.MIN_PREMIUM:
            return False
        if not tx.verify():
            return False
        if tx.nonce <= self.nonces.get(tx.from_addr, 0):
            return False
        reserved = self.reserved.get(tx.from_addr, 0)
        if self.balances.get(tx.from_addr, 0) < reserved + tx.premium:
            return False
        if tx.type == "dsl":
            try:
                dsl.parse_script(tx.script)
            except Exception:
                return False
        elif not _valid_governance_data(tx):
            return False
        tx_hash = tx.hash()
        if tx_hash in self.tx_hashes:
            return False
        self._insert(tx, tx_hash)
        return True

    def _insert(self, tx: Transaction, tx_hash: str) -> None:
        self.txs.append((self._seq, tx))
        self.tx_hashes.add(tx_hash)
        self.nonces[tx.from_addr] = max(self.nonces.get(tx.from_addr, 0), tx.nonce)
        self.reserved[tx.from_addr] = self.reserved.get(tx.from_addr, 0) + tx.premium
        self._seq += 1
        self._reorder()

    def pop_for_block(self, cap: int) -> List[Transaction]:
        selected = self.txs[:cap]
        self.txs = self.txs[cap:]
        for _, tx in selected:
            self.tx_hashes.discard(tx.hash())
            self.reserved[tx.from_addr] = max(0, self.reserved.get(tx.from_addr, 0) - tx.premium)
        return [tx for _, tx in selected]

    def drop_confirmed(self, chain_nonces: Dict[str, int]) -> None:
        """Drop pooled transactions already included on-chain (nonce <= chain max)."""
        kept: List[Tuple[int, Transaction]] = []
        for seq, tx in self.txs:
            if tx.nonce <= chain_nonces.get(tx.from_addr, 0):
                self.tx_hashes.discard(tx.hash())
                self.reserved[tx.from_addr] = max(0, self.reserved.get(tx.from_addr, 0) - tx.premium)
            else:
                kept.append((seq, tx))
        self.txs = kept

    def requeue(self, txs: List[Transaction]) -> None:
        """Re-admit transactions from an expired (never finalized) candidate.

        They were valid when first admitted, so signature/nonce checks are
        skipped; duplicates already in the pool are ignored.
        """
        for tx in txs:
            tx_hash = tx.hash()
            if tx_hash in self.tx_hashes:
                continue
            self._insert(tx, tx_hash)

    def __len__(self) -> int:
        return len(self.txs)
