from typing import List
from .transaction import Transaction

class Mempool:
    def __init__(self, mode: str = "premium"):
        self.mode = mode
        self._seq = 0
        self.txs: List[tuple[int, Transaction]] = []

    def add_tx(self, tx: Transaction):
        self.txs.append((self._seq, tx))
        self._seq += 1
        if self.mode == "premium":
            self.txs.sort(key=lambda item: (-item[1].premium, item[0]))

    def pop_for_block(self, cap: int) -> List[Transaction]:
        selected_pairs = self.txs[:cap]
        self.txs = self.txs[cap:]
        return [tx for _, tx in selected_pairs]
