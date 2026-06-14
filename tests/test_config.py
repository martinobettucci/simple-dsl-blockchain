import os
import json

import pytest

from blockchain_demo.config import load_config, apply_data_dir, Config


def test_load_config_from_json(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"QUORUM_PERCENT": 60, "DIFFICULTY_BITS": 10}))
    cfg = load_config(str(cfg_path))
    assert cfg.QUORUM_PERCENT == 60
    assert cfg.DIFFICULTY_BITS == 10
    # unknown keys are ignored, defaults applied for the rest
    assert cfg.BLOCK_TX_CAP == 3


def test_load_config_from_py(tmp_path):
    cfg_path = tmp_path / "cfg.py"
    cfg_path.write_text("QUORUM_PERCENT = 55\nTX_QUEUE_MODE = 'fifo'\nUNKNOWN = 1\n")
    cfg = load_config(str(cfg_path))
    assert cfg.QUORUM_PERCENT == 55
    assert cfg.TX_QUEUE_MODE == "fifo"


def test_load_config_invalid_quorum(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"QUORUM_PERCENT": 101}))
    with pytest.raises(ValueError):
        load_config(str(cfg_path))


def test_load_config_invalid_mode(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"TX_QUEUE_MODE": "lifo"}))
    with pytest.raises(ValueError):
        load_config(str(cfg_path))


def test_load_config_does_not_create_dirs(tmp_path):
    # load_config must not create storage dirs as a global side effect
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"BLOCKS_DIR": str(tmp_path / "nope")}))
    cfg = load_config(str(cfg_path))
    assert not os.path.isdir(cfg.BLOCKS_DIR)


def test_apply_data_dir_creates_per_node_paths(tmp_path):
    cfg = Config()
    data_dir = str(tmp_path / "miner")
    apply_data_dir(cfg, data_dir)
    assert cfg.BLOCKS_DIR == os.path.join(data_dir, "blocks")
    assert cfg.PENDING_DIR == os.path.join(data_dir, "pending")
    assert cfg.STATE_FILE == os.path.join(data_dir, "state.json")
    assert os.path.isdir(cfg.BLOCKS_DIR)
    assert os.path.isdir(cfg.PENDING_DIR)
