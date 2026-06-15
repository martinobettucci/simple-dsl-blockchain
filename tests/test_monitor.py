"""Per-node monitoring endpoints + the explorer's node directory."""

import os

import pytest

from blockchain_demo.node import ChainState, create_app
from blockchain_demo.network import ChainStore
from blockchain_demo.block import Block, BlockHeader, GENESIS_HASH
from blockchain_demo.transaction import Transaction
from blockchain_demo.config import governable_dict
from blockchain_demo.governance import GovernanceState

pytestmark = pytest.mark.p1


def _node(cfg_fast, tmp_path, validators, user):
    vset = [v["public_key"] for v in validators]
    g0 = GovernanceState(validators=sorted(vset), config=governable_dict(cfg_fast),
                         miss_counts={v: 0 for v in vset}, last_signed_height={v: 0 for v in vset})
    genesis = Block(BlockHeader(GENESIS_HASH, 0, 0, 0, "genesis"), [], {"counter": 0},
                    {user["public_key"]: 100}, finalized=True, governance=g0.to_snapshot())
    dd = os.path.join(tmp_path, "n")
    os.makedirs(os.path.join(dd, "blocks"))
    os.makedirs(os.path.join(dd, "pending"))
    store = ChainStore(os.path.join(dd, "blocks"), os.path.join(dd, "pending"),
                       os.path.join(dd, "state.json"), os.path.join(dd, "balances.json"))
    store.save_block(genesis)
    return ChainState(cfg_fast, validators[0], "validator", 9555, store, peers=[])


def test_monitor_endpoints(cfg_fast, tmp_path, make_wallet, validators):
    user = make_wallet("user")
    client = create_app(_node(cfg_fast, tmp_path, validators, user)).test_client()

    assert client.get("/monitor").status_code == 200          # UI page is served

    st = client.get("/stats").get_json()
    assert st["role"] == "validator" and st["height"] == 0 and "counters" in st

    tx = Transaction(user["public_key"], "let counter = counter + 1", 2, 1).sign(user)
    assert client.post("/tx", json=tx.to_json()).get_json()["status"] == "accepted"
    mp = client.get("/mempool").get_json()
    assert mp["size"] == 1 and mp["mempool"][0]["from"] == user["public_key"]
    assert client.get("/stats").get_json()["counters"]["tx_accepted"] == 1

    g = client.get("/graph").get_json()
    assert any(b["genesis"] and b["canonical"] for b in g["blocks"])

    bd = client.get("/block/" + GENESIS_HASH).get_json()
    assert bd["block"]["header"]["height"] == 0
    assert client.get("/block/deadbeef").status_code == 404

    assert "logs" in client.get("/logs").get_json()


def test_explorer_nodes_directory(tmp_path, monkeypatch):
    from blockchain_demo import explorer, network

    def fake_status(url, timeout=2.0):
        if "9000" in url:
            return {"role": "archive", "is_archive": True, "height": 5, "pubkey": None}
        return {"role": "validator", "is_archive": False, "height": 5, "pubkey": "abcd"}

    monkeypatch.setattr(network, "fetch_status", fake_status)
    monkeypatch.setattr(network, "fetch_peers",
                        lambda url, timeout=2.0: [{"host": "127.0.0.1", "port": 9002}])

    dd = os.path.join(tmp_path, "a")
    os.makedirs(os.path.join(dd, "blocks"))
    os.makedirs(os.path.join(dd, "pending"))
    app = explorer.create_app(os.path.join(dd, "blocks"), os.path.join(dd, "pending"),
                              os.path.join(dd, "state.json"), os.path.join(dd, "balances.json"),
                              node_url="http://127.0.0.1:9000")
    nodes = app.test_client().get("/nodes").get_json()["nodes"]

    assert sorted(n["port"] for n in nodes) == [9000, 9002]
    assert any(n["is_archive"] for n in nodes)
    assert all(n["monitor"].endswith("/monitor") for n in nodes)
