import os
import json
import shutil
import subprocess
from blockchain_demo.wallet import generate_wallet
from blockchain_demo.block import Block, BlockHeader
from blockchain_demo.config import CFG

WALLET_DIR = "wallets"
BLOCKS_DIR = os.path.join("blockchain_demo", "blocks")


def clean_runtime():
    if os.path.exists(WALLET_DIR):
        shutil.rmtree(WALLET_DIR)
    if os.path.exists(BLOCKS_DIR):
        shutil.rmtree(BLOCKS_DIR)
    for fname in ["state.json", "balances.json", "validators.json"]:
        path = os.path.join("blockchain_demo", fname)
        if os.path.exists(path):
            os.remove(path)


def launch_node(role: str, wallet_path: str):
    return subprocess.Popen(
        ["python", "blockchain_demo/node_stub.py", "--role", role, "--wallet", wallet_path],
        start_new_session=True,
    )


def main():
    clean_runtime()

    os.makedirs(WALLET_DIR, exist_ok=True)
    validators = []
    validator_paths = []
    balances = {}

    # 1- create validators wallets
    for idx, name in enumerate(["Val-A", "Val-B", "Val-C"], start=1):
        path = os.path.join(WALLET_DIR, f"validator{idx}.json")
        wallet_data = generate_wallet(path, local_role="validator")
        validators.append({"pubkey": wallet_data["public_key"], "name": name})
        balances[wallet_data["public_key"]] = 100
        validator_paths.append(path)

    # 2- create miner wallet
    miner_path = os.path.join(WALLET_DIR, "miner.json")
    miner_wallet = generate_wallet(miner_path, local_role="miner")
    balances[miner_wallet["public_key"]] = 0

    # 3- create user wallet
    user_path = os.path.join(WALLET_DIR, "user.json")
    user_wallet = generate_wallet(user_path, local_role="user")
    balances[user_wallet["public_key"]] = 1000

    validators_json = {"validators": validators, "quorum_percent": CFG.QUORUM_PERCENT}
    with open(os.path.join("blockchain_demo", "validators.json"), "w") as f:
        json.dump(validators_json, f, indent=2)

    state = {"counter": 0}
    with open(os.path.join("blockchain_demo", "state.json"), "w") as f:
        json.dump({"state": state}, f, indent=2)
    with open(os.path.join("blockchain_demo", "balances.json"), "w") as f:
        json.dump({"balances": balances}, f, indent=2)

    # 4- create genesis block giving user some coins
    header = BlockHeader(prev_hash="0" * 64, height=0, nonce=0, timestamp=0, miner="genesis")
    genesis_block = Block(
        header=header,
        transactions=[],
        state=state,
        balances=balances,
        finalized=True,
        validator_signatures={},
        signers_frozen=[],
    )
    genesis_json = genesis_block.to_json()
    genesis_json["hash"] = "0" * 64
    os.makedirs(BLOCKS_DIR, exist_ok=True)
    with open(os.path.join(BLOCKS_DIR, "0000000000000000000000000000000000000000000000000000000000000000.json"), "w") as f:
        json.dump(genesis_json, f, indent=2)

    # launch miner and validators
    launch_node("miner", miner_path)
    for path in validator_paths:
        launch_node("validator", path)

if __name__ == '__main__':
    main()
