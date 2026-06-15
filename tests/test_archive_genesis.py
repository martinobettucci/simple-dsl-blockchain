"""The archive builds the genesis block from a bootstrap spec; a synced node
derives G_0 (initial validators + bootstrap config) from it."""

import pytest

from blockchain_demo.node import build_genesis_from_spec
from blockchain_demo.block import block_id, GENESIS_HASH
from blockchain_demo.config import Config, governable_dict
from blockchain_demo.governance import genesis_state, quorum_at, calc_quorum

pytestmark = pytest.mark.p0


def test_archive_builds_genesis(make_wallet, cfg_fast):
    validators = [make_wallet("validator") for _ in range(3)]
    vset = [v["public_key"] for v in validators]
    spec = {
        "validators": [{"pubkey": v["public_key"]} for v in validators],
        "config": governable_dict(cfg_fast),
        "balances": {validators[0]["public_key"]: 100},
        "state": {"counter": 0},
    }
    g = build_genesis_from_spec(spec)

    assert g.is_genesis()
    assert block_id(g) == GENESIS_HASH
    assert g.finalized and g.balances[validators[0]["public_key"]] == 100

    gs = genesis_state(g)
    assert gs.validators == sorted(vset)
    assert gs.config["QUORUM_PERCENT"] == cfg_fast.QUORUM_PERCENT
    assert quorum_at(gs) == calc_quorum(3, cfg_fast.QUORUM_PERCENT)
