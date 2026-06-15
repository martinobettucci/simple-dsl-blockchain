"""Web wallet (server-side signing) that talks to a node's RPC API.

The wallet holds no chain state.  It derives the public key from a private key,
reads balance/nonce from an RPC node (``GET /account``), and builds + signs a DSL
statement transaction with the canonical :mod:`wallet` before relaying it
(``POST /tx``) — exactly the real-world flow where the wallet signs and the RPC
node only relays the signed transaction (``eth_sendRawTransaction``).

Signing happens server-side (reusing ``wallet.py`` so signatures always verify),
so the private key is sent from the browser to THIS local wallet server.  That is
a pedagogical convenience, not a hardware-wallet security model — the UI says so.
"""

import argparse
import os

import requests
from flask import Flask, request, jsonify, send_from_directory

from . import wallet as wallet_mod
from .network import base_url
from .transaction import Transaction

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def build_signed_tx(private_key: str, script: str, premium: int, nonce: int) -> Transaction:
    """Build and sign a DSL statement transaction (pure, network-free)."""
    pub = wallet_mod.public_key_of(private_key)
    tx = Transaction(pub, script, int(premium), int(nonce))
    tx.sign({"private_key": private_key})
    return tx


def create_app(default_rpc: str = "") -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

    def _rpc(value: str) -> str:
        return base_url(value or default_rpc)

    def _body():
        return request.get_json(force=True, silent=True) or {}

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "wallet.html")

    @app.get("/api/config")
    def config():
        return jsonify({"rpc": default_rpc})

    @app.post("/api/derive")
    def derive():
        try:
            return jsonify({"public_key": wallet_mod.public_key_of(_body().get("private_key", "").strip())})
        except Exception:
            return jsonify({"error": "invalid private key"}), 400

    @app.get("/api/account")
    def account():
        rpc, pubkey = _rpc(request.args.get("rpc", "")), request.args.get("pubkey", "")
        try:
            return jsonify(requests.get(f"{rpc}/account/{pubkey}", timeout=4).json())
        except Exception as e:
            return jsonify({"error": f"rpc unreachable: {e}"}), 502

    @app.post("/api/send")
    def send():
        b = _body()
        pk, script = b.get("private_key", "").strip(), b.get("script", "")
        premium, rpc = int(b.get("premium", 0) or 0), _rpc(b.get("rpc", ""))
        try:
            pub = wallet_mod.public_key_of(pk)
        except Exception:
            return jsonify({"error": "invalid private key"}), 400
        try:
            nonce = int(requests.get(f"{rpc}/account/{pub}", timeout=4).json().get("next_nonce", 1))
        except Exception as e:
            return jsonify({"error": f"rpc unreachable: {e}"}), 502
        tx = build_signed_tx(pk, script, premium, nonce)
        try:
            res = requests.post(f"{rpc}/tx", json=tx.to_json(), timeout=4).json()
        except Exception as e:
            return jsonify({"error": f"relay failed: {e}"}), 502
        return jsonify({"submitted": res, "tx_hash": tx.hash(), "nonce": nonce, "from": pub})

    return app


def main():
    p = argparse.ArgumentParser(description="Web wallet (server-side signing)")
    p.add_argument("--rpc", default="http://127.0.0.1:9006", help="default RPC node endpoint")
    p.add_argument("--port", type=int, default=8700)
    args = p.parse_args()
    print(f"Wallet on http://127.0.0.1:{args.port}  (RPC {args.rpc})")
    create_app(default_rpc=args.rpc).run(host="127.0.0.1", port=args.port,
                                         threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
