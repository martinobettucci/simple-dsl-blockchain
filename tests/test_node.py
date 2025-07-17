import os
import json
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from genesys import main as genesys_main
from blockchain_demo.node import Node
from blockchain_demo.wallet import generate_wallet
from blockchain_demo.transaction import Transaction


def setup_project(tmp_path):
    project = Path(tmp_path)
    shutil.copytree("blockchain_demo", project / "blockchain_demo")
    cwd = os.getcwd()
    os.chdir(project)
    genesys_main()
    return project, cwd


def test_mining_without_validator_signatures(tmp_path):
    project, cwd = setup_project(tmp_path)
    try:
        miner_wallet = generate_wallet(project / "wallets" / "miner.json", local_role="miner")
        node = Node(wallet_path=str(project / "wallets" / "miner.json"))
        tx = Transaction(from_addr=miner_wallet["public_key"], script="let counter=1", premium=1, nonce=1)
        tx.sign(miner_wallet)
        node.submit_tx(tx)
        block = node.mine_block()
        assert not block.finalized
    finally:
        os.chdir(cwd)
