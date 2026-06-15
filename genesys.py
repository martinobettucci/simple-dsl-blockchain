"""Bootstrap and launch the demo blockchain as a real multi-process mesh.

There is no shared on-disk protocol state anymore.  The flow is:

  1. create wallets (validators first, so their pubkeys go into the genesis spec);
  2. write a genesis bootstrap spec (initial validators + governable config +
     initial balances/state) — the only common hard-coded data;
  3. start the ARCHIVE node (no wallet): it builds the genesis block from the
     spec and serves sync;
  4. start miner + validators with ``--bootstrap=<archive>``: each has only its
     wallet and syncs the chain from the archive, then discovers the mesh by
     gossip;
  5. start the web explorer (derives validators/config from the chain);
  6. submit demo DSL transactions, then a governance demo: a brand-new node
     joins via the archive, applies to become a validator and is voted in.

    python genesys.py               # full demo
    python genesys.py --no-demo-tx  # bootstrap only
    python genesys.py --no-gov-demo # skip the vote-in-a-validator demo
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

from blockchain_demo.config import load_config, governable_dict
from blockchain_demo.wallet import generate_wallet, next_nonce
from blockchain_demo.transaction import Transaction

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(ROOT, "runtime")
WALLET_DIR = os.path.join(RUNTIME, "wallets")

ARCHIVE_PORT = 9000
EXPLORER_PORT = 8600
RPC_PORT = 9006        # passive RPC node the wallet talks to
WALLET_PORT = 8700     # web wallet app
# (name, role, port) for the initial validator-bearing nodes
NODES = [
    ("miner", "miner", 9001),
    ("validator1", "validator", 9002),
    ("validator2", "validator", 9003),
    ("validator3", "validator", 9004),
]
CANDIDATE = ("candidate", "validator", 9005)   # joins later in the governance demo

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


def wait_for(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def submit(url, wallet, wallet_path, *, script="", premium=0, type_="dsl", data=None):
    nonce = next_nonce(wallet, wallet_path)
    tx = Transaction(wallet["public_key"], script, premium, nonce, type=type_, data=data or {})
    tx.sign(wallet)
    try:
        r = requests.post(url + "/tx", json=tx.to_json(), timeout=3).json()
        return r.get("status")
    except Exception as e:
        return f"failed ({e})"


def launch_node(args, name, role, port, *, bootstrap=None, wallet=True, genesis_spec=None):
    cmd = [sys.executable, "-m", "blockchain_demo.node",
           "--config", args.config, "--local-role", role,
           "--port", str(port), "--data-dir", os.path.join(RUNTIME, name)]
    if wallet:
        cmd += ["--wallet", os.path.join(WALLET_DIR, f"{name}.json")]
    if bootstrap:
        cmd += ["--bootstrap", bootstrap]
    if genesis_spec:
        cmd += ["--genesis-spec", genesis_spec]
    return subprocess.Popen(cmd, cwd=ROOT, start_new_session=True)


def main():
    parser = argparse.ArgumentParser(description="Bootstrap the demo blockchain")
    parser.add_argument("--config", default=os.path.join(ROOT, "config.demo.json"))
    parser.add_argument("--no-demo-tx", action="store_true", help="do not auto-submit demo transactions")
    parser.add_argument("--no-gov-demo", action="store_true", help="skip the vote-in-a-validator demo")
    args = parser.parse_args()
    cfg = load_config(args.config)

    clean_runtime()

    # 1) wallets (validators first) + initial balances
    miner_w = generate_wallet(os.path.join(WALLET_DIR, "miner.json"), local_role="miner")
    balances = {miner_w["public_key"]: 0}
    validator_ws = []
    for i in range(1, 4):
        w = generate_wallet(os.path.join(WALLET_DIR, f"validator{i}.json"), local_role="validator")
        validator_ws.append(w)
        balances[w["public_key"]] = 100
    user_w = generate_wallet(os.path.join(WALLET_DIR, "user.json"), local_role="user")
    balances[user_w["public_key"]] = 1000
    cand_w = generate_wallet(os.path.join(WALLET_DIR, "candidate.json"), local_role="validator")
    balances[cand_w["public_key"]] = 100

    # 2) genesis bootstrap spec (the only common hard-coded data)
    spec = {
        "validators": [{"pubkey": w["public_key"], "name": f"Val-{i+1}"}
                       for i, w in enumerate(validator_ws)],
        "config": governable_dict(cfg),
        "balances": balances,
        "state": {"counter": 0},
    }
    spec_file = os.path.join(RUNTIME, "genesis_spec.json")
    with open(spec_file, "w") as f:
        json.dump(spec, f, indent=2)

    archive_url = f"http://127.0.0.1:{ARCHIVE_PORT}"
    procs = []

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

    # 3) archive (no wallet) builds the genesis and serves sync
    procs.append(launch_node(args, "archive", "archive", ARCHIVE_PORT,
                             wallet=False, genesis_spec=spec_file))
    if not wait_for(archive_url + "/status"):
        print("ERROR: archive did not start"); shutdown()

    # 4) miner + validators bootstrap from the archive (sync genesis + chain)
    for name, role, port in NODES:
        procs.append(launch_node(args, name, role, port, bootstrap=archive_url))

    # 4b) a passive RPC node (no wallet): syncs, serves reads, relays signed txs
    rpc_url = f"http://127.0.0.1:{RPC_PORT}"
    procs.append(launch_node(args, "rpc", "rpc", RPC_PORT, bootstrap=archive_url, wallet=False))

    # 5) explorer derives everything from the archive's copy of the chain
    procs.append(subprocess.Popen(
        [sys.executable, "-m", "blockchain_demo.explorer",
         "--data-dir", os.path.join(RUNTIME, "archive"),
         "--node-url", archive_url, "--port", str(EXPLORER_PORT)],
        cwd=ROOT, start_new_session=True))

    # 5b) web wallet (server-side signing) pointed at the RPC node
    wait_for(rpc_url + "/status")
    procs.append(subprocess.Popen(
        [sys.executable, "-m", "blockchain_demo.wallet_app",
         "--rpc", rpc_url, "--port", str(WALLET_PORT)],
        cwd=ROOT, start_new_session=True))

    ready = all(wait_for(f"http://127.0.0.1:{port}/status") for _, _, port in NODES)
    print("\n=== Demo blockchain running (mesh) ===")
    print(f"  Explorer : http://127.0.0.1:{EXPLORER_PORT}   (Network nodes · /governance)")
    print(f"  Wallet   : http://127.0.0.1:{WALLET_PORT}   (web wallet -> RPC {rpc_url})")
    print(f"  Archive  : {archive_url}/monitor   (no wallet, creates genesis, sync source)")
    print(f"  RPC node : {rpc_url}/monitor   (passive: sync + serve reads + relay tx)")
    for name, role, port in NODES:
        print(f"  {name:11s} role={role:9s} http://127.0.0.1:{port}/monitor  --bootstrap {archive_url}")
    print("  (each node exposes /monitor: mempool, logs, run stats, fork graph, topology)")
    print("\n  Paste this demo user key into the Wallet app (balance 1000):")
    print(f"    private key: {user_w['private_key']}")
    print(f"    public key : {user_w['public_key']}")
    print(f"  quorum={cfg.QUORUM_PERCENT}%  difficulty={cfg.DIFFICULTY_BITS} bits  "
          f"offline_N={cfg.LIVENESS_OFFLINE_N}  miss_X={cfg.LIVENESS_MISS_X}  floor={cfg.VALIDATOR_FLOOR}")
    if not ready:
        print("  WARNING: some nodes did not become ready in time")

    miner_url = f"http://127.0.0.1:{NODES[0][2]}"
    user_path = os.path.join(WALLET_DIR, "user.json")

    if ready:
        print("\nletting the mesh form (peer discovery + sync)...")
        time.sleep(8)  # so every validator is discovered before blocks are produced

    # 6) demo DSL transactions (mixed premiums -> anti-censure ordering)
    if not args.no_demo_tx and ready:
        print("submitting demo transactions:")
        for premium, script in DEMO_TXS:
            status = submit(miner_url, user_w, user_path, script=script, premium=premium)
            print(f"  premium={premium:2d} -> {status}")
            time.sleep(1.2)  # one block at a time, with the full validator set present

    # 7) governance demo: a new node joins and is voted in as a validator
    if not args.no_gov_demo and ready:
        name, role, port = CANDIDATE
        print(f"\n=== governance demo: '{name}' joins via the archive and applies ===")
        procs.append(launch_node(args, name, role, port, bootstrap=archive_url))
        wait_for(f"http://127.0.0.1:{port}/status")
        time.sleep(2)  # let it sync + mesh
        cand_path = os.path.join(WALLET_DIR, "candidate.json")
        print("  apply ->", submit(miner_url, cand_w, cand_path, type_="validator_apply"))
        for i, w in enumerate(validator_ws[:2], 1):  # two votes reach quorum (of 3)
            vp = os.path.join(WALLET_DIR, f"validator{i}.json")
            print(f"  vote v{i} ->", submit(miner_url, w, vp, type_="validator_vote",
                                            data={"candidate": cand_w["public_key"]}))
        # poll the chain-derived governance until the candidate is admitted
        for _ in range(15):
            time.sleep(1)
            try:
                gov = requests.get(archive_url + "/governance", timeout=2).json()
            except Exception:
                continue
            if cand_w["public_key"] in gov.get("validators", []):
                print(f"  ADMITTED: validator set now has {len(gov['validators'])} "
                      f"validators, quorum={gov['quorum']}")
                break
        else:
            print("  (candidate not yet admitted — check the explorer /governance)")

    print("\nPress Ctrl-C to stop.\n")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
