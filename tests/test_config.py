import os
import json
import pytest
from blockchain_demo.config import load_config, CFG


def test_load_config_from_json(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    blocks = tmp_path / "b"
    pending = tmp_path / "p"
    data = {
        "QUORUM_PERCENT": 60,
        "BLOCKS_DIR": str(blocks),
        "PENDING_DIR": str(pending),
    }
    cfg_path.write_text(json.dumps(data))
    cfg = load_config(str(cfg_path))
    assert cfg.QUORUM_PERCENT == 60
    assert os.path.isdir(cfg.BLOCKS_DIR)
    assert os.path.isdir(cfg.PENDING_DIR)


def test_load_config_invalid_quorum(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"QUORUM_PERCENT": 101}))
    with pytest.raises(ValueError):
        load_config(str(cfg_path))


def test_load_config_from_py(tmp_path):
    cfg_path = tmp_path / "cfg.py"
    blocks = tmp_path / "bb"
    pending = tmp_path / "pp"
    cfg_path.write_text(
        f"QUORUM_PERCENT = 55\nBLOCKS_DIR = r'{blocks}'\nPENDING_DIR = r'{pending}'\n"
    )
    cfg = load_config(str(cfg_path))
    assert cfg.QUORUM_PERCENT == 55
    assert os.path.isdir(cfg.BLOCKS_DIR)
    assert os.path.isdir(cfg.PENDING_DIR)
