"""Read-only web explorer (Flask) over a node's data directory.

Reuses :class:`ChainStore` and reloads from disk per request — no consensus
state of its own.  Serves the REST API (§6.2/§12) plus a minimal static UI that
makes the economics visible (all ``validator_signatures`` vs the paid
``signers_frozen``, premium ordering, state/balance diffs, forks).
"""

import argparse
import os
from typing import Dict, Optional, Tuple

from flask import Flask, jsonify, send_from_directory

from . import network
from .network import ChainStore
from .block import block_id
from .governance import fold_chain, quorum_at, GovernanceState

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(blocks_dir: str, pending_dir: str, state_file: str, bal_file: str,
               node_url: str = None) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    store = ChainStore(blocks_dir, pending_dir, state_file, bal_file)

    def gov_tip() -> Tuple[Optional[GovernanceState], list]:
        """Fold the canonical chain into its tip governance state (validators +
        config derived from the chain, no shared files)."""
        ch = store.select_canonical_chain(store.load_all_blocks())
        if not ch:
            return None, ch
        try:
            return fold_chain(ch)[-1], ch
        except Exception:
            return None, ch

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
        gtip, _ = gov_tip()
        quorum = quorum_at(gtip) if gtip else 0
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
        gtip, ch = gov_tip()
        if gtip is None:
            return jsonify({"validators": [], "quorum": 0, "count": 0, "config": {}})
        stats = {v: {"pubkey": v, "signed": 0, "paid_blocks": 0,
                     "miss_count": gtip.miss_counts.get(v, 0),
                     "last_signed": gtip.last_signed_height.get(v, 0)}
                 for v in gtip.validators}
        for b in ch:
            for pk in b.validator_signatures:
                if pk in stats:
                    stats[pk]["signed"] += 1
            for pk in b.signers_frozen:
                if pk in stats:
                    stats[pk]["paid_blocks"] += 1
        return jsonify({"validators": list(stats.values()),
                        "quorum": quorum_at(gtip), "count": len(stats), "config": gtip.config})

    @app.get("/governance")
    def governance():
        gtip, _ = gov_tip()
        if gtip is None:
            return jsonify({"validators": [], "quorum": 0, "config": {},
                            "applications": {}, "config_proposals": {}})
        return jsonify(gtip.to_snapshot())

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
        # The mesh peer list is live consensus state; proxy it from a node if one
        # is linked, otherwise report none (the explorer is disk-only by default).
        if not node_url:
            return jsonify({"peers": []})
        try:
            return jsonify({"peers": network.fetch_peers(node_url)})
        except Exception:
            return jsonify({"peers": []})

    @app.get("/nodes")
    def nodes():
        """Directory of discovered nodes (linked node + its mesh peers), probed
        server-side so the UI can deep-link to each node's own /monitor page."""
        if not node_url:
            return jsonify({"nodes": []})
        seen: Dict[str, dict] = {}

        def probe(url: str):
            try:
                st = network.fetch_status(url)
            except Exception:
                return
            ep = network.parse_endpoint(network.base_url(url))
            seen[f"{ep.host}:{ep.port}"] = {
                "url": network.base_url(url), "host": ep.host, "port": ep.port,
                "role": st.get("role"), "is_archive": st.get("is_archive"),
                "height": st.get("height"), "pubkey": st.get("pubkey"),
                "monitor": f"{network.base_url(url)}/monitor",
            }

        probe(node_url)
        try:
            for p in network.fetch_peers(node_url):
                probe(f"http://{p['host']}:{p['port']}")
        except Exception:
            pass
        return jsonify({"nodes": sorted(seen.values(), key=lambda n: n["port"])})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Blockchain web explorer")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--node-url", help="optional node endpoint to proxy live /peers")
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    app = create_app(
        os.path.join(args.data_dir, "blocks"),
        os.path.join(args.data_dir, "pending"),
        os.path.join(args.data_dir, "state.json"),
        os.path.join(args.data_dir, "balances.json"),
        node_url=args.node_url,
    )
    print(f"Explorer on http://127.0.0.1:{args.port}")
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
