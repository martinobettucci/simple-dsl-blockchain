import os

import pytest

from blockchain_demo.config import Config
from blockchain_demo import wallet as wallet_mod
from blockchain_demo.block import Block, BlockHeader, GENESIS_HASH


@pytest.fixture
def cfg_fast():
    """Fast, deterministic protocol config for tests (low PoW difficulty)."""
    return Config(
        DIFFICULTY_BITS=8,
        QUORUM_PERCENT=51,
        BLOCK_REWARD=5,
        BLOCK_TX_CAP=3,
        MIN_PREMIUM=0,
        TX_QUEUE_MODE="premium",
        PREMIUM_REMAINDER_TARGET="miner",
    )


@pytest.fixture
def make_wallet(tmp_path):
    """Factory creating fresh wallets in the test's tmp dir."""
    counter = {"i": 0}

    def _make(role="user"):
        counter["i"] += 1
        path = os.path.join(tmp_path, f"wallet_{counter['i']}.json")
        return wallet_mod.generate_wallet(path, local_role=role)

    return _make


@pytest.fixture
def validators(make_wallet):
    """Three validator wallets; ``[w['public_key'] ...]`` is the validator set."""
    return [make_wallet("validator") for _ in range(3)]


@pytest.fixture
def tmp_data_dir(tmp_path):
    d = os.path.join(tmp_path, "node")
    os.makedirs(os.path.join(d, "blocks"))
    os.makedirs(os.path.join(d, "pending"))
    return d


@pytest.fixture
def genesis_block(validators, cfg_fast):
    """Standard genesis embedding the initial governance snapshot (validators +
    bootstrap config), so the chain can be folded into governance state."""
    from blockchain_demo.config import governable_dict
    from blockchain_demo.governance import GovernanceState
    vset = sorted(v["public_key"] for v in validators)
    g0 = GovernanceState(validators=vset, config=governable_dict(cfg_fast),
                         miss_counts={v: 0 for v in vset},
                         last_signed_height={v: 0 for v in vset})
    header = BlockHeader(prev_hash=GENESIS_HASH, height=0, nonce=0, timestamp=0, miner="genesis")
    return Block(
        header=header,
        transactions=[],
        state={"counter": 0},
        balances={},
        finalized=True,
        governance=g0.to_snapshot(),
    )
