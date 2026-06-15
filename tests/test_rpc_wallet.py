"""RPC read endpoint (/account), the passive `rpc` role, and the web wallet."""

import os

import pytest

from blockchain_demo.node import ChainState, create_app
from blockchain_demo.network import ChainStore
from blockchain_demo.block import Block, BlockHeader, GENESIS_HASH
from blockchain_demo.transaction import Transaction
from blockchain_demo.config import governable_dict
from blockchain_demo.governance import GovernanceState
from blockchain_demo import wallet_app

pytestmark = pytest.mark.p1


def _node(cfg_fast, tmp_path, validators, user, role="validator", wallet=None):
    vset = [v["public_key"] for v in validators]
    g0 = GovernanceState(validators=sorted(vset), config=governable_dict(cfg_fast),
                         miss_counts={v: 0 for v in vset}, last_signed_height={v: 0 for v in vset})
    genesis = Block(BlockHeader(GENESIS_HASH, 0, 0, 0, "genesis"), [], {"counter": 0},
                    {user["public_key"]: 1000}, finalized=True, governance=g0.to_snapshot())
    dd = os.path.join(tmp_path, role)
    os.makedirs(os.path.join(dd, "blocks"))
    os.makedirs(os.path.join(dd, "pending"))
    store = ChainStore(os.path.join(dd, "blocks"), os.path.join(dd, "pending"),
                       os.path.join(dd, "state.json"), os.path.join(dd, "balances.json"))
    store.save_block(genesis)
    return ChainState(cfg_fast, wallet, role, 9600, store, peers=[])


def test_account_balance_and_nonce(cfg_fast, tmp_path, make_wallet, validators):
    user = make_wallet("user")
    client = create_app(_node(cfg_fast, tmp_path, validators, user, wallet=validators[0])).test_client()
    acct = client.get("/account/" + user["public_key"]).get_json()
    assert acct["balance"] == 1000 and acct["nonce"] == 0 and acct["next_nonce"] == 1

    tx = Transaction(user["public_key"], "let counter = counter + 1", 2, 1).sign(user)
    assert client.post("/tx", json=tx.to_json()).get_json()["status"] == "accepted"
    acct2 = client.get("/account/" + user["public_key"]).get_json()
    assert acct2["nonce"] == 1 and acct2["next_nonce"] == 2     # floor bumped by the pooled tx


def test_rpc_role_is_passive(cfg_fast, tmp_path, make_wallet, validators):
    user = make_wallet("user")
    state = _node(cfg_fast, tmp_path, validators, user, role="rpc", wallet=None)
    assert state.supports_mining is False and state.supports_validation is False
    assert state.is_archive is False and state.pubkey is None

    client = create_app(state).test_client()
    assert client.get("/account/" + user["public_key"]).get_json()["balance"] == 1000
    tx = Transaction(user["public_key"], "let counter = counter + 1", 0, 1).sign(user)
    assert client.post("/tx", json=tx.to_json()).get_json()["status"] == "accepted"  # relays
    state.mine_once()
    assert state.tip_hash == GENESIS_HASH                       # never produces a block


def test_wallet_build_signed_tx_verifies(make_wallet):
    w = make_wallet("user")
    tx = wallet_app.build_signed_tx(w["private_key"], "let counter = counter + 1", 3, 5)
    assert tx.from_addr == w["public_key"] and tx.verify()
    assert tx.nonce == 5 and tx.premium == 3 and tx.type == "dsl"


def test_wallet_derive_and_send(make_wallet, monkeypatch):
    w = make_wallet("user")
    client = wallet_app.create_app(default_rpc="http://rpc.test").test_client()

    assert client.post("/api/derive", json={"private_key": w["private_key"]}).get_json()["public_key"] == w["public_key"]
    assert client.post("/api/derive", json={"private_key": "zzz"}).status_code == 400

    captured = {}

    class _R:
        def __init__(self, j): self._j = j
        def json(self): return self._j

    monkeypatch.setattr(wallet_app.requests, "get", lambda url, timeout=4: _R({"next_nonce": 7, "balance": 50}))

    def fake_post(url, json=None, timeout=4):
        captured["url"] = url
        captured["tx"] = json
        return _R({"status": "accepted"})

    monkeypatch.setattr(wallet_app.requests, "post", fake_post)

    res = client.post("/api/send", json={"private_key": w["private_key"],
                                         "script": "let counter = counter + 1", "premium": 2}).get_json()
    assert res["nonce"] == 7 and res["from"] == w["public_key"]
    relayed = Transaction.from_json(captured["tx"])
    assert captured["url"].endswith("/tx")
    assert relayed.verify() and relayed.nonce == 7 and relayed.from_addr == w["public_key"]
