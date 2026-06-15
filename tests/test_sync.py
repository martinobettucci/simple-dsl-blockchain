"""Sync feeds finalized blocks through the normal validation path: a fresh node
converges on the same tip AND derived governance, and rejects tampered blocks."""

import copy
import os

import pytest

from blockchain_demo.network import ChainStore
from blockchain_demo.node import ChainState
from blockchain_demo.block import block_id, GENESIS_HASH
from tests.helpers import signed_tx, finalized_block

pytestmark = pytest.mark.p0


def _store(d):
    os.makedirs(os.path.join(d, "blocks"), exist_ok=True)
    os.makedirs(os.path.join(d, "pending"), exist_ok=True)
    return ChainStore(os.path.join(d, "blocks"), os.path.join(d, "pending"),
                      os.path.join(d, "state.json"), os.path.join(d, "balances.json"))


@pytest.fixture
def chain(cfg_fast, genesis_block, make_wallet, validators):
    miner = make_wallet("miner")
    vset = [v["public_key"] for v in validators]
    b1 = finalized_block(cfg_fast, genesis_block, miner, validators, vset,
                         [signed_tx(miner, premium=0, nonce=1)])
    b2 = finalized_block(cfg_fast, b1, miner, validators, vset,
                         [signed_tx(miner, premium=0, nonce=2)])
    return genesis_block, b1, b2, vset


def _fresh_node(cfg, tmp_path, make_wallet):
    return ChainState(cfg, make_wallet("user"), "full", 0, _store(str(tmp_path)), peers=[])


def test_sync_converges_tip_and_governance(chain, cfg_fast, tmp_path, make_wallet):
    genesis, b1, b2, vset = chain
    node = _fresh_node(cfg_fast, tmp_path, make_wallet)
    for blk in (genesis, b1, b2):  # height order, through on_block_finalized
        assert node.on_block_finalized(blk.to_json())["status"] == "ok"
    assert node.tip_hash == block_id(b2)
    assert node.governance_summary()["validators"] == sorted(vset)


def test_sync_rejects_tampered_balances(chain, cfg_fast, tmp_path, make_wallet):
    genesis, b1, b2, _ = chain
    node = _fresh_node(cfg_fast, tmp_path, make_wallet)
    node.on_block_finalized(genesis.to_json())
    node.on_block_finalized(b1.to_json())
    bad = copy.deepcopy(b2.to_json())
    bad["balances"][b2.header.miner] = 999999
    assert node.on_block_finalized(bad)["status"] == "invalid"


def test_sync_rejects_tampered_governance(chain, cfg_fast, tmp_path, make_wallet):
    genesis, b1, b2, _ = chain
    node = _fresh_node(cfg_fast, tmp_path, make_wallet)
    node.on_block_finalized(genesis.to_json())
    node.on_block_finalized(b1.to_json())
    bad = copy.deepcopy(b2.to_json())
    bad["governance"]["validators"] = sorted(bad["governance"]["validators"] + ["deadbeef"])
    assert node.on_block_finalized(bad)["status"] == "invalid"
