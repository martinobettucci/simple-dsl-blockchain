from typing import Dict, List, Optional, Set
from .transaction import Transaction
from . import dsl
from .config import CFG

class Mempool:
    def __init__(self, balances: Optional[Dict[str, int]] = None, mode: Optional[str] = None):
        self.mode = mode or CFG.TX_QUEUE_MODE
        self._seq = 0
        self.txs: List[tuple[int, Transaction]] = []
        self.tx_hashes: Set[str] = set()
        self.nonces: Dict[str, int] = {}
        self.balances = balances or {}

    def add_tx(self, tx: Transaction) -> bool:
        # verify signature
        if not tx.verify():
            return False
        # verify nonce monotonic per address
        if tx.nonce <= self.nonces.get(tx.from_addr, 0):
            return False
        # verify balance sufficient for premium
        if self.balances.get(tx.from_addr, 0) < tx.premium:
            return False
        # pre-parse DSL script
        try:
            dsl.parse_script(tx.script)
        except Exception:
            return False
        tx_hash = tx.hash()
        if tx_hash in self.tx_hashes:
            return False

        self.txs.append((self._seq, tx))
        self.tx_hashes.add(tx_hash)
        self.nonces[tx.from_addr] = tx.nonce
        self._seq += 1
        if self.mode == "premium":
            self.txs.sort(key=lambda item: (-item[1].premium, item[0]))
        return True

    def pop_for_block(self, cap: int) -> List[Transaction]:
        selected_pairs = self.txs[:cap]
        self.txs = self.txs[cap:]
        for _, tx in selected_pairs:
            self.tx_hashes.discard(tx.hash())
        return [tx for _, tx in selected_pairs]
