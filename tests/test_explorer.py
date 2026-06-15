import os
import json

import pytest

from blockchain_demo.explorer import create_app
from blockchain_demo.network import ChainStore
from blockchain_demo.block import block_id, GENESIS_HASH
from tests.helpers import signed_tx, finalized_block


@pytest.fixture
def seeded(cfg_fast, tmp_data_dir, genesis_block, make_wallet, validators):
    paths = dict(
        blocks_dir=os.path.join(tmp_data_dir, "blocks"),
        pending_dir=os.path.join(tmp_data_dir, "pending"),
        state_file=os.path.join(tmp_data_dir, "state.json"),
        bal_file=os.path.join(tmp_data_dir, "balances.json"),
    )
    store = ChainStore(**paths)
    store.save_block(genesis_block)
    miner = make_wallet("miner")
    vset = [v["public_key"] for v in validators]
    blk = finalized_block(cfg_fast, genesis_block, miner, validators, vset,
                          [signed_tx(miner, premium=4)])
    store.save_block(blk)
    store.save_state(blk.state)
    store.save_balances(blk.balances)
    app = create_app(**paths)
    return app.test_client(), blk, miner, vset


def test_chain_ordered(seeded):
    client, blk, _, _ = seeded
    data = client.get("/chain").get_json()
    hashes = [b["hash"] for b in data["chain"]]
    assert hashes == [GENESIS_HASH, block_id(blk)]
    assert data["height"] == 1


def test_block_endpoint(seeded):
    client, blk, _, _ = seeded
    data = client.get(f"/block/{block_id(blk)}").get_json()
    assert data["hash"] == block_id(blk)
    assert "validator_signatures" in data and "signers_frozen" in data
    assert client.get("/block/deadbeef").status_code == 404


def test_validators_stats(seeded):
    client, blk, _, vset = seeded
    data = client.get("/validators").get_json()
    assert data["quorum"] == 2
    paid = {v["pubkey"]: v["paid_blocks"] for v in data["validators"]}
    for v in blk.signers_frozen:
        assert paid[v] == 1


def test_diff_shows_reward(seeded):
    client, blk, miner, _ = seeded
    data = client.get(f"/diff/{block_id(blk)}").get_json()
    # miner balance went from absent to BLOCK_REWARD(+remainder)
    assert miner["public_key"] in data["balances_diff"]
    assert data["state_diff"]["counter"]["to"] == 1


def test_balances_and_state(seeded):
    client, blk, _, _ = seeded
    assert client.get("/state").get_json()["state"] == blk.state
    assert client.get("/balances").get_json()["balances"] == blk.balances
