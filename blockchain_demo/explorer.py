"""Read-only web explorer (Flask) over a node's data directory.

Reuses :class:`ChainStore` and reloads from disk per request — no consensus
state of its own.  Serves the REST API (§6.2/§12) plus a minimal static UI that
makes the economics visible (all ``validator_signatures`` vs the paid
``signers_frozen``, premium ordering, state/balance diffs, forks).
"""

import argparse
import json
import os
from typing import Dict

from flask import Flask, jsonify, send_from_directory

from .network import ChainStore, load_peers, discover_peers
from .block import block_id, calc_quorum

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(blocks_dir: str, pending_dir: str, state_file: str, bal_file: str,
               validators_file: str = None, peers_file: str = None) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    store = ChainStore(blocks_dir, pending_dir, state_file, bal_file)

    def validators_doc() -> Dict:
        if validators_file and os.path.exists(validators_file):
            with open(validators_file) as f:
                return json.load(f)
        return {"validators": [], "quorum_percent": 51}

    def quorum_of(doc: Dict) -> int:
        n = len(doc.get("validators", []))
        return calc_quorum(n, doc.get("quorum_percent", 51)) if n else 0

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/chain")
    def chain():
        ch = store.select_canonical_chain(store.load_all_blocks())
        return jsonify({"chain": [b.to_json() for b in ch],
                        "height": ch[-1].header.height if ch else 0})

    @app.get("/branches")
    def branches():
        blocks = store.load_all_blocks()
        graph = store.build_fork_graph(blocks)
        tips = [bid for bid in blocks if bid not in graph]  # blocks with no children
        out = []
        for bid in tips:
            ch = store._chain_to(bid, blocks)
            if ch:
                out.append({"tip": bid, "length": len(ch),
                            "total_pow": sum(store.total_pow(b) for b in ch),
                            "blocks": [block_id(b) for b in ch]})
        out.sort(key=lambda x: -x["length"])
        return jsonify({"branches": out})

    @app.get("/pending")
    def pending():
        doc = validators_doc()
        quorum = quorum_of(doc)
        out = [{"hash": bid, "height": b.header.height, "miner": b.header.miner,
                "signatures": len(b.validator_signatures), "signers_frozen": b.signers_frozen,
                "quorum": quorum, "finalized": b.finalized}
               for bid, b in store.load_pending().items()]
        return jsonify({"pending": out, "quorum": quorum})

    @app.get("/block/<bhash>")
    def block(bhash):
        b = store.load_all_blocks().get(bhash) or store.load_pending().get(bhash)
        if not b:
            return jsonify({"error": "not found"}), 404
        return jsonify(b.to_json())

    @app.get("/state")
    def state():
        return jsonify({"state": store.load_state()})

    @app.get("/balances")
    def balances():
        return jsonify({"balances": store.load_balances()})

    @app.get("/tx/<txhash>")
    def tx(txhash):
        for status, coll in (("finalized", store.load_all_blocks()),
                             ("pending", store.load_pending())):
            for bid, b in coll.items():
                for t in b.transactions:
                    if t.hash() == txhash:
                        return jsonify({"tx": t.to_json(), "block": bid, "status": status})
        return jsonify({"error": "not found"}), 404

    @app.get("/address/<pubkey>")
    def address(pubkey):
        ch = store.select_canonical_chain(store.load_all_blocks())
        txs = [{"tx": t.to_json(), "block": block_id(b)}
               for b in ch for t in b.transactions if t.from_addr == pubkey]
        return jsonify({"address": pubkey, "balance": store.load_balances().get(pubkey, 0),
                        "transactions": txs})

    @app.get("/validators")
    def validators():
        doc = validators_doc()
        stats = {e["pubkey"]: {"pubkey": e["pubkey"], "name": e.get("name"),
                               "signed": 0, "paid_blocks": 0}
                 for e in doc.get("validators", [])}
        for b in store.select_canonical_chain(store.load_all_blocks()):
            for pk in b.validator_signatures:
                if pk in stats:
                    stats[pk]["signed"] += 1
            for pk in b.signers_frozen:
                if pk in stats:
                    stats[pk]["paid_blocks"] += 1
        return jsonify({"validators": list(stats.values()),
                        "quorum": quorum_of(doc), "count": len(stats)})

    @app.get("/diff/<bhash>")
    def diff(bhash):
        blocks = store.load_all_blocks()
        b = blocks.get(bhash)
        if not b:
            return jsonify({"error": "not found"}), 404
        parent = blocks.get(b.header.prev_hash)
        p_state = parent.state if parent else {}
        p_bal = parent.balances if parent else {}

        def delta(new, old):
            return {k: {"from": old.get(k), "to": v} for k, v in new.items() if old.get(k) != v}

        return jsonify({"state_diff": delta(b.state, p_state),
                        "balances_diff": delta(b.balances, p_bal)})

    @app.get("/peers")
    def peers():
        if not peers_file or not os.path.exists(peers_file):
            return jsonify({"peers": []})
        plist = load_peers(peers_file)
        vset = [x["pubkey"] for x in validators_doc().get("validators", [])]
        discover_peers(plist, vset)
        return jsonify({"peers": [p.to_dict() for p in plist]})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Blockchain web explorer")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--validators", required=True)
    parser.add_argument("--peers", required=True)
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    app = create_app(
        os.path.join(args.data_dir, "blocks"),
        os.path.join(args.data_dir, "pending"),
        os.path.join(args.data_dir, "state.json"),
        os.path.join(args.data_dir, "balances.json"),
        args.validators, args.peers,
    )
    print(f"Explorer on http://127.0.0.1:{args.port}")
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
