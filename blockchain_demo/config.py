from dataclasses import dataclass, asdict
import json
import importlib.util
import os

@dataclass
class Config:
    BLOCK_TX_CAP: int = 3
    BLOCK_REWARD: int = 5
    MIN_PREMIUM: int = 0
    TX_QUEUE_MODE: str = "premium"
    QUORUM_PERCENT: int = 51
    DIFFICULTY_BITS: int = 20
    DATA_DIR: str = "./"
    BLOCKS_DIR: str = "./blocks"
    PENDING_DIR: str = "./pending"
    STATE_FILE: str = "state.json"
    BAL_FILE: str = "balances.json"
    VALIDATORS_FILE: str = "validators.json"
    PEERS_FILE: str = "peers.json"
    API_PORT: int = 8545
    LOCAL_ROLE: str = "miner"
    BLOCK_CANDIDATE_TTL: int = 120
    PREMIUM_REFUND_ON_FAIL: bool = True
    PREMIUM_REMAINDER_TARGET: str = "miner"

CFG = Config()


def load_config(path: str) -> Config:
    """Load configuration from a JSON or Python file.

    Parameters
    ----------
    path: str
        Path to a ``.json`` or ``.py`` file describing configuration
        values. Unknown keys are ignored.

    Returns
    -------
    Config
        Parsed configuration instance assigned to ``CFG``.
    """

    defaults = asdict(Config())
    data = {}
    if path.endswith(".json"):
        with open(path) as fh:
            data = json.load(fh)
    elif path.endswith(".py"):
        spec = importlib.util.spec_from_file_location("_user_cfg", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)  # type: ignore[arg-type]
        data = {k: getattr(module, k) for k in defaults.keys() if hasattr(module, k)}
    else:
        raise ValueError("Unsupported config format")

    defaults.update({k: v for k, v in data.items() if k in defaults})
    cfg = Config(**defaults)

    if not 1 <= cfg.QUORUM_PERCENT <= 100:
        raise ValueError("QUORUM_PERCENT must be between 1 and 100")

    os.makedirs(cfg.BLOCKS_DIR, exist_ok=True)
    os.makedirs(cfg.PENDING_DIR, exist_ok=True)

    global CFG
    CFG = cfg
    return cfg

