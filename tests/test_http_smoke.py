"""Real-socket smoke test for the node's Flask RPC layer."""

import os
import socket
import threading

import pytest
import requests
from werkzeug.serving import make_server

from blockchain_demo.node import ChainState, create_app
from blockchain_demo.network import ChainStore
from blockchain_demo.block import Block, BlockHeader, GENESIS_HASH
from blockchain_demo.transaction import Transaction
from blockchain_demo import wallet as wallet_mod


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.network
@pytest.mark.slow
def test_node_http_endpoints(cfg_fast, tmp_path, make_wallet, validators):
    user = make_wallet("user")
    vset = [v["public_key"] for v in validators]
    genesis = Block(BlockHeader(GENESIS_HASH, 0, 0, 0, "genesis"), [],
                    {"counter": 0}, {user["public_key"]: 100}, finalized=True)
    dd = os.path.join(tmp_path, "n")
    os.makedirs(os.path.join(dd, "blocks"))
    os.makedirs(os.path.join(dd, "pending"))
    store = ChainStore(os.path.join(dd, "blocks"), os.path.join(dd, "pending"),
                       os.path.join(dd, "state.json"), os.path.join(dd, "balances.json"))
    store.save_block(genesis)
    state = ChainState(cfg_fast, validators[0], "validator", 0, store, vset, peers=[])
    srv = make_server("127.0.0.1", _free_port(), create_app(state), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        status = requests.get(base + "/status", timeout=3).json()
        assert status["supports_validation"] is True
        assert status["height"] == 0

        nonce = "ab" * 16
        rc = requests.post(base + "/role_challenge", json={"nonce": nonce}, timeout=3).json()
        assert wallet_mod.verify(rc["pubkey"], nonce, rc["signature"])

        tx = Transaction(user["public_key"], "let counter = counter + 1", 2, 1)
        tx.sign(user)
        resp = requests.post(base + "/tx", json=tx.to_json(), timeout=3).json()
        assert resp["status"] == "accepted"
        assert resp["tx_hash"] == tx.hash()
    finally:
        srv.shutdown()
