import json
import hashlib
import time
from dataclasses import dataclass, field
from typing import List, Dict
from .transaction import Transaction
from . import dsl


def sha256d(data: bytes) -> str:
    return hashlib.sha256(hashlib.sha256(data).digest()).hexdigest()


@dataclass
class BlockHeader:
    prev_hash: str
    height: int
    nonce: int
    timestamp: int
    miner: str

    def to_dict(self):
        return {
            "prev_hash": self.prev_hash,
            "height": self.height,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
            "miner": self.miner,
        }


@dataclass
class Block:
    header: BlockHeader
    transactions: List[Transaction]
    state: Dict[str, int]
    balances: Dict[str, int]
    validator_signatures: Dict[str, str] = field(default_factory=dict)
    finalized: bool = False
    signers_frozen: List[str] = field(default_factory=list)

    def canonical_dict(self):
        return {
            "header": self.header.to_dict(),
            "transactions": [tx.to_json() for tx in self.transactions],
            "state": self.state,
            "balances": self.balances,
        }

    def hash(self):
        data = json.dumps(self.canonical_dict(), separators=(",", ":"), sort_keys=True).encode()
        return sha256d(data)

    @classmethod
    def create_candidate(cls, prev_hash: str, height: int, miner: str, txs: List[Transaction], parent_state: Dict[str, int], parent_balances: Dict[str, int]):
        state = parent_state.copy()
        for tx in txs:
            state = dsl.execute(tx.script, state)
        balances = parent_balances.copy()
        header = BlockHeader(prev_hash=prev_hash, height=height, nonce=0, timestamp=int(time.time()), miner=miner)
        return cls(header=header, transactions=txs, state=state, balances=balances)

    def proof_of_work(self, difficulty_bits: int):
        target = 2 ** (256 - difficulty_bits)
        nonce = 0
        while True:
            self.header.nonce = nonce
            if int(self.hash(), 16) < target:
                break
            nonce += 1

    def to_json(self):
        data = self.canonical_dict()
        data.update({
            "hash": self.hash(),
            "validator_signatures": self.validator_signatures,
            "finalized": self.finalized,
            "signers_frozen": self.signers_frozen,
        })
        return data
