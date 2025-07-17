import json
import hashlib
import time
from dataclasses import dataclass, field
from typing import List, Dict
from math import ceil
from .wallet import verify
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

    def add_validator_signature(self, pubkey: str, signature: str, validator_set: List[str]) -> bool:
        if pubkey not in validator_set:
            return False
        if not verify(pubkey, self.hash(), signature):
            return False
        self.validator_signatures[pubkey] = signature
        return True

    def finalize(self, validator_set: List[str], parent_balances: Dict[str, int], cfg):
        quorum = ceil(len(validator_set) * cfg.QUORUM_PERCENT / 100)
        signers = [v for v in validator_set if v in self.validator_signatures] #also check again valid signature to add to the list
        if len(signers) < quorum:
            raise ValueError("quorum not reached")
        premiums_total = sum(tx.premium for tx in self.transactions)
        share = premiums_total // len(signers) if signers else 0
        remainder = premiums_total % len(signers) if signers else 0
        balances = parent_balances.copy()
        balances[self.header.miner] = balances.get(self.header.miner, 0) + cfg.BLOCK_REWARD
        for v in signers:
            balances[v] = balances.get(v, 0) + share
        if remainder and cfg.PREMIUM_REMAINDER_TARGET == "miner":
            balances[self.header.miner] = balances.get(self.header.miner, 0) + remainder
        self.balances = balances
        self.signers_frozen = sorted(signers)
        self.finalized = True
        return self
