"""Bootstrap and launch the demo blockchain (multi-process).

Creates wallets, the shared ``validators.json`` / ``peers.json``, seeds an
identical genesis block into each node's data directory, then launches one
miner + three validators + the web explorer as separate processes.  Nodes are
started as modules (``python -m blockchain_demo.node``) so package imports
resolve.  A few demo transactions are submitted so the chain visibly produces
blocks.

    python genesys.py            # run the demo
    python genesys.py --no-demo-tx   # bootstrap without auto transactions
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

import requests

from blockchain_demo.config import load_config
from blockchain_demo.wallet import generate_wallet, next_nonce
from blockchain_demo.transaction import Transaction
from blockchain_demo.block import Block, BlockHeader, GENESIS_HASH
from blockchain_demo.network import ChainStore

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(ROOT, "runtime")
WALLET_DIR = os.path.join(RUNTIME, "wallets")
EXPLORER_PORT = 8600

# (node name == wallet name == data dir, role, port)
NODES = [
    ("miner", "miner", 9001),
    ("validator1", "validator", 9002),
    ("validator2", "validator", 9003),
    ("validator3", "validator", 9004),
]

DEMO_TXS = [
    (10, "let counter = counter + 1"),
    (2, "let counter = counter + 1"),
    (5, "let counter = counter + 1"),
    (7, "let counter = counter + 1"),
    (1, "let counter = counter + 1"),
]


def clean_runtime():
    if os.path.exists(RUNTIME):
        shutil.rmtree(RUNTIME)
    os.makedirs(WALLET_DIR)


def seed_genesis(data_dir, state, balances):
    os.makedirs(os.path.join(data_dir, "blocks"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "pending"), exist_ok=True)
    store = ChainStore(
        os.path.join(data_dir, "blocks"), os.path.join(data_dir, "pending"),
        os.path.join(data_dir, "state.json"), os.path.join(data_dir, "balances.json"),
    )
    genesis = Block(BlockHeader(GENESIS_HASH, 0, 0, 0, "genesis"), [],
                    dict(state), dict(balances), finalized=True)
    store.save_block(genesis)
    store.save_state(state)
    store.save_balances(balances)


def wait_for(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    parser = argparse.ArgumentParser(description="Bootstrap the demo blockchain")
    parser.add_argument("--config", default=os.path.join(ROOT, "config.demo.json"))
    parser.add_argument("--no-demo-tx", action="store_true",
                        help="do not auto-submit demo transactions")
    args = parser.parse_args()
    cfg = load_config(args.config)

    clean_runtime()

    # 1) wallets + initial balances
    miner_w = generate_wallet(os.path.join(WALLET_DIR, "miner.json"), local_role="miner")
    balances = {miner_w["public_key"]: 0}
    validators_entries = []
    for i in range(1, 4):
        w = generate_wallet(os.path.join(WALLET_DIR, f"validator{i}.json"), local_role="validator")
        validators_entries.append({"pubkey": w["public_key"], "name": f"Val-{i}"})
        balances[w["public_key"]] = 100
    user_w = generate_wallet(os.path.join(WALLET_DIR, "user.json"), local_role="user")
    balances[user_w["public_key"]] = 1000

    # 2) shared registry files (no roles in peers.json — discovered at runtime)
    validators_file = os.path.join(RUNTIME, "validators.json")
    with open(validators_file, "w") as f:
        json.dump({"validators": validators_entries, "quorum_percent": cfg.QUORUM_PERCENT}, f, indent=2)
    peers_file = os.path.join(RUNTIME, "peers.json")
    with open(peers_file, "w") as f:
        json.dump({"peers": [{"host": "127.0.0.1", "port": port} for _, _, port in NODES]}, f, indent=2)

    # 3) seed identical genesis into each node's data dir
    state = {"counter": 0}
    for name, _, _ in NODES:
        seed_genesis(os.path.join(RUNTIME, name), state, balances)

    # 4) launch nodes (as modules) + explorer
    procs = []
    for name, role, port in NODES:
        cmd = [sys.executable, "-m", "blockchain_demo.node",
               "--config", args.config, "--local-role", role,
               "--wallet", os.path.join(WALLET_DIR, f"{name}.json"),
               "--port", str(port), "--data-dir", os.path.join(RUNTIME, name),
               "--peers", peers_file, "--validators", validators_file]
        procs.append(subprocess.Popen(cmd, cwd=ROOT, start_new_session=True))
    procs.append(subprocess.Popen(
        [sys.executable, "-m", "blockchain_demo.explorer",
         "--data-dir", os.path.join(RUNTIME, "miner"),
         "--validators", validators_file, "--peers", peers_file,
         "--port", str(EXPLORER_PORT)],
        cwd=ROOT, start_new_session=True))

    def shutdown(*_):
        print("\nstopping nodes...")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 5) wait for nodes to bind
    ready = all(wait_for(f"http://127.0.0.1:{port}/status") for _, _, port in NODES)
    print("\n=== Demo blockchain running ===")
    print(f"  Explorer : http://127.0.0.1:{EXPLORER_PORT}")
    for name, role, port in NODES:
        print(f"  {name:11s} role={role:9s} http://127.0.0.1:{port}")
    print(f"  quorum={cfg.QUORUM_PERCENT}%  difficulty={cfg.DIFFICULTY_BITS} bits  tx_cap={cfg.BLOCK_TX_CAP}")
    if not ready:
        print("  WARNING: some nodes did not become ready in time")

    # 6) demo transactions from the user wallet (mixed premiums -> anti-censure)
    if not args.no_demo_tx and ready:
        miner_url = f"http://127.0.0.1:{NODES[0][2]}"
        user_path = os.path.join(WALLET_DIR, "user.json")
        print("\nsubmitting demo transactions:")
        for premium, script in DEMO_TXS:
            nonce = next_nonce(user_w, user_path)
            tx = Transaction(user_w["public_key"], script, premium, nonce)
            tx.sign(user_w)
            try:
                r = requests.post(miner_url + "/tx", json=tx.to_json(), timeout=3).json()
                print(f"  premium={premium:2d} nonce={nonce} -> {r.get('status')}")
            except Exception as e:
                print(f"  premium={premium:2d} nonce={nonce} -> failed ({e})")
            time.sleep(0.4)

    print("\nPress Ctrl-C to stop.\n")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
