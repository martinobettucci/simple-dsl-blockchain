import os
import json
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from genesys import main as genesys_main


def test_genesys_creates_genesis(tmp_path):
    project = Path(tmp_path)
    os.makedirs(project / "blockchain_demo")
    shutil.copytree("blockchain_demo", project / "blockchain_demo", dirs_exist_ok=True)
    cwd = os.getcwd()
    os.chdir(project)
    try:
        genesys_main()
    finally:
        os.chdir(cwd)
    # wallets created
    for idx in range(1, 4):
        assert (project / "wallets" / f"validator{idx}.json").exists()
    # genesis block
    genesis_path = project / "blockchain_demo" / "blocks" / ("0"*64 + ".json")
    assert genesis_path.exists()
    data = json.load(open(genesis_path))
    assert data["header"]["height"] == 0
    assert data["finalized"] is True
    assert data["validator_signatures"] == {}
    assert data["signers_frozen"] == []
