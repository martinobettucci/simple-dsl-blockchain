"""Block model, Proof-of-Work, validator signature aggregation, finalization.

Block identity (``hash()``) is a double SHA-256 over the canonical form
``{header, transactions, state}`` only.  ``balances`` is deliberately EXCLUDED
(see ``canonical_dict``): rewards and premium distribution depend on
``signers_frozen``, which is only known at finalization, while validators sign
the block hash earlier — so the identity must be stable from candidate through
finalized.  ``balances`` is still part of the serialized block (§4.7), just not
of the hash.  Integrity of finalized balances is re-checked on receipt by
recomputing ``finalize`` from the parent's balances.
"""

import json
import hashlib
import time
from dataclasses import dataclass, field
from math import ceil
from typing import Dict, List

from .wallet import verify
from .transaction import Transaction
from . import dsl

GENESIS_HASH = "0" * 64


def sha256d(data: bytes) -> str:
    return hashlib.sha256(hashlib.sha256(data).digest()).hexdigest()


def calc_quorum(n: int, percent: int) -> int:
    """Numeric quorum = ceil(N * percent / 100) (§11.1)."""
    return ceil(n * percent / 100)


def distribute_rewards(miner: str, transactions, signers, parent_balances: Dict[str, int], cfg) -> Dict[str, int]:
    """Balances after debiting premiums and paying out the block (§5.7, §10.6).

    Conservation: each sender is debited its premium (charged at finalization,
    §5.3); the total is split equally among ``signers`` with the remainder going
    to the miner (or burned).  Only ``BLOCK_REWARD`` is newly minted.  Shared by
    :meth:`Block.finalize` and the node's finalized-block validation so both
    compute the exact same distribution.
    """
    balances = dict(parent_balances)
    # debit premiums from each transaction sender
    for tx in transactions:
        balances[tx.from_addr] = balances.get(tx.from_addr, 0) - tx.premium
    premiums_total = sum(tx.premium for tx in transactions)
    n = len(signers)
    share = premiums_total // n if n else 0
    remainder = premiums_total - share * n
    # newly minted block reward to the miner
    balances[miner] = balances.get(miner, 0) + cfg.BLOCK_REWARD
    for v in signers:
        balances[v] = balances.get(v, 0) + share
    if remainder and cfg.PREMIUM_REMAINDER_TARGET == "miner":
        balances[miner] = balances.get(miner, 0) + remainder
    # PREMIUM_REMAINDER_TARGET == "burn": remainder is simply not credited.
    return balances


@dataclass
class BlockHeader:
    prev_hash: str
    height: int
    nonce: int
    timestamp: int
    miner: str

    def to_dict(self) -> Dict:
        return {
            "prev_hash": self.prev_hash,
            "height": self.height,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
            "miner": self.miner,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "BlockHeader":
        return cls(
            prev_hash=d["prev_hash"],
            height=int(d["height"]),
            nonce=int(d["nonce"]),
            timestamp=int(d["timestamp"]),
            miner=d["miner"],
        )


@dataclass
class Block:
    header: BlockHeader
    transactions: List[Transaction]
    state: Dict[str, int]
    balances: Dict[str, int]
    validator_signatures: Dict[str, str] = field(default_factory=dict)
    finalized: bool = False
    signers_frozen: List[str] = field(default_factory=list)

    def canonical_dict(self) -> Dict:
        return {
            "header": self.header.to_dict(),
            "transactions": [tx.to_json() for tx in self.transactions],
            "state": self.state,
        }

    def hash(self) -> str:
        data = json.dumps(self.canonical_dict(), separators=(",", ":"), sort_keys=True).encode()
        return sha256d(data)

    def is_genesis(self) -> bool:
        return self.header.height == 0 and self.header.prev_hash == GENESIS_HASH

    @classmethod
    def create_candidate(cls, prev_hash: str, height: int, miner: str,
                         txs: List[Transaction], parent_state: Dict[str, int],
                         parent_balances: Dict[str, int], cfg) -> "Block":
        state = dict(parent_state)
        for tx in txs:
            state = dsl.execute(tx.script, state)
        # Provisional balances for display only (excluded from the hash, and
        # recomputed at finalize once signers_frozen is known).
        balances = dict(parent_balances)
        balances[miner] = balances.get(miner, 0) + cfg.BLOCK_REWARD
        header = BlockHeader(prev_hash=prev_hash, height=height, nonce=0,
                             timestamp=int(time.time()), miner=miner)
        return cls(header=header, transactions=list(txs), state=state, balances=balances)

    def proof_of_work(self, difficulty_bits: int) -> "Block":
        target = 1 << (256 - difficulty_bits)
        nonce = 0
        while True:
            self.header.nonce = nonce
            if int(self.hash(), 16) < target:
                break
            nonce += 1
        return self

    def has_valid_pow(self, difficulty_bits: int) -> bool:
        return int(self.hash(), 16) < (1 << (256 - difficulty_bits))

    def to_json(self) -> Dict:
        data = self.canonical_dict()
        data.update({
            "hash": GENESIS_HASH if self.is_genesis() else self.hash(),
            "balances": self.balances,
            "validator_signatures": self.validator_signatures,
            "finalized": self.finalized,
            "signers_frozen": self.signers_frozen,
        })
        return data

    @classmethod
    def from_json(cls, data: Dict) -> "Block":
        return cls(
            header=BlockHeader.from_dict(data["header"]),
            transactions=[Transaction.from_json(t) for t in data["transactions"]],
            state=dict(data.get("state", {})),
            balances=dict(data.get("balances", {})),
            validator_signatures=dict(data.get("validator_signatures", {})),
            finalized=bool(data.get("finalized", False)),
            signers_frozen=list(data.get("signers_frozen", [])),
        )

    def add_validator_signature(self, pubkey: str, signature: str, validator_set: List[str]) -> bool:
        """Aggregate a validator signature over this block's hash (non-ordered)."""
        if pubkey not in validator_set:
            return False
        if not verify(pubkey, self.hash(), signature):
            return False
        self.validator_signatures[pubkey] = signature
        return True

    def signer_count(self, validator_set: List[str]) -> int:
        return sum(1 for v in validator_set if v in self.validator_signatures)

    def finalize(self, validator_set: List[str], parent_balances: Dict[str, int], cfg) -> "Block":
        """Freeze signers and distribute rewards once quorum is reached (§5.7).

        Idempotent: a late signature must not re-trigger reward distribution
        (otherwise the miner reward and premiums would be paid twice).
        """
        if self.finalized:
            return self
        quorum = calc_quorum(len(validator_set), cfg.QUORUM_PERCENT)
        signers = [v for v in validator_set if v in self.validator_signatures]
        if len(signers) < quorum:
            raise ValueError("quorum not reached")
        self.balances = distribute_rewards(self.header.miner, self.transactions, signers, parent_balances, cfg)
        self.signers_frozen = sorted(signers)
        self.finalized = True
        return self


def block_id(block: Block) -> str:
    """Stable identifier / filename for a block.

    Genesis keeps the literal zero hash (its content is not a real PoW); every
    other block is identified by its computed hash.
    """
    if block.is_genesis():
        return GENESIS_HASH
    return block.hash()
