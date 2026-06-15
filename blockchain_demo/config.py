"""Protocol configuration for the pedagogical blockchain.

The :class:`Config` dataclass holds every protocol parameter documented in
``SPECIFICATIONS.md`` §8.  Configuration can be loaded from a ``.json`` file or
a ``.py`` file exposing module level constants whose names match the dataclass
fields.  Unknown keys are ignored so configs stay forward compatible.

``load_config`` only *parses and validates* — it never creates directories as a
global side effect (several nodes run from the same working directory).  Path
resolution for a given node is done explicitly via :func:`apply_data_dir`, which
rewrites the per-node storage paths under a dedicated data directory.
"""

from dataclasses import dataclass, asdict, fields, replace
import json
import importlib.util
import os


@dataclass
class Config:
    BLOCK_TX_CAP: int = 3
    BLOCK_REWARD: int = 5
    MIN_PREMIUM: int = 0
    TX_QUEUE_MODE: str = "premium"          # "premium" or "fifo"
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
    LOCAL_ROLE: str = "miner"               # miner / validator / both / full / archive / rpc
    BLOCK_CANDIDATE_TTL: int = 120
    SIGNATURE_GRACE: float = 0.0            # secs the proposer waits to gather all signatures
    PREMIUM_REFUND_ON_FAIL: bool = True
    PREMIUM_REMAINDER_TARGET: str = "miner"  # "miner" or "burn"
    # On-chain governance (liveness-based auto-removal + safety floor)
    LIVENESS_OFFLINE_N: int = 20            # remove if unsigned for more than N blocks
    LIVENESS_MISS_X: int = 10               # remove if cumulative missed-quorum reaches X
    VALIDATOR_FLOOR: int = 1                # never auto-remove below this many validators
    BOOTSTRAP: str = ""                     # bootstrap peer "host:port" (per-node, CLI)


# Protocol parameters that can be changed on-chain via a config_propose/config_vote
# transaction.  Everything else is per-node bootstrap/CLI state.
GOVERNABLE_KEYS = {
    "BLOCK_REWARD", "MIN_PREMIUM", "QUORUM_PERCENT", "DIFFICULTY_BITS",
    "BLOCK_TX_CAP", "PREMIUM_REMAINDER_TARGET", "TX_QUEUE_MODE",
    "LIVENESS_OFFLINE_N", "LIVENESS_MISS_X", "VALIDATOR_FLOOR",
}


# Global, replaced by load_config.  Modules that need defaults import CFG.
CFG = Config()


def _validate(cfg: Config) -> None:
    if not 1 <= cfg.QUORUM_PERCENT <= 100:
        raise ValueError("QUORUM_PERCENT must be between 1 and 100")
    if cfg.TX_QUEUE_MODE not in ("premium", "fifo"):
        raise ValueError("TX_QUEUE_MODE must be 'premium' or 'fifo'")
    if cfg.PREMIUM_REMAINDER_TARGET not in ("miner", "burn"):
        raise ValueError("PREMIUM_REMAINDER_TARGET must be 'miner' or 'burn'")
    if cfg.DIFFICULTY_BITS < 1 or cfg.DIFFICULTY_BITS > 256:
        raise ValueError("DIFFICULTY_BITS must be between 1 and 256")
    if cfg.BLOCK_TX_CAP < 1:
        raise ValueError("BLOCK_TX_CAP must be >= 1")
    if cfg.LIVENESS_OFFLINE_N < 1:
        raise ValueError("LIVENESS_OFFLINE_N must be >= 1")
    if cfg.LIVENESS_MISS_X < 1:
        raise ValueError("LIVENESS_MISS_X must be >= 1")
    if cfg.VALIDATOR_FLOOR < 1:
        raise ValueError("VALIDATOR_FLOOR must be >= 1")
    if cfg.SIGNATURE_GRACE < 0:
        raise ValueError("SIGNATURE_GRACE must be >= 0")


def load_config(path: str) -> Config:
    """Load configuration from a ``.json`` or ``.py`` file.

    Returns a validated :class:`Config` and assigns it to the global ``CFG``.
    Unknown keys are ignored.  No directories are created here.
    """
    defaults = asdict(Config())
    field_names = {f.name for f in fields(Config)}

    if path.endswith(".json"):
        with open(path) as fh:
            data = json.load(fh)
    elif path.endswith(".py"):
        spec = importlib.util.spec_from_file_location("_user_cfg", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        data = {k: getattr(module, k) for k in field_names if hasattr(module, k)}
    else:
        raise ValueError("Unsupported config format (use .json or .py)")

    defaults.update({k: v for k, v in data.items() if k in field_names})
    cfg = Config(**defaults)
    _validate(cfg)

    global CFG
    CFG = cfg
    return cfg


def effective_config(base: Config, gov_config: dict) -> Config:
    """Overlay the on-chain governable values onto a node's bootstrap config.

    Used so consensus code (PoW difficulty, quorum, reward, tx cap…) reads the
    config that is active *at a given chain position* (the parent governance
    snapshot) while keeping per-node bootstrap fields (paths, ports) intact.
    """
    overrides = {k: gov_config[k] for k in GOVERNABLE_KEYS if k in gov_config}
    return replace(base, **overrides)


def governable_dict(cfg: Config) -> dict:
    """The governable subset of a config, for embedding in the genesis snapshot."""
    return {k: getattr(cfg, k) for k in GOVERNABLE_KEYS}


def apply_data_dir(cfg: Config, data_dir: str) -> Config:
    """Point a node's storage paths at ``data_dir`` and create the directories.

    Each node owns an isolated data directory so several nodes can run on the
    same machine without sharing block/pending storage.  ``validators.json`` and
    ``peers.json`` stay shared (resolved from their own CLI paths), so they are
    left untouched here.
    """
    cfg.DATA_DIR = data_dir
    cfg.BLOCKS_DIR = os.path.join(data_dir, "blocks")
    cfg.PENDING_DIR = os.path.join(data_dir, "pending")
    cfg.STATE_FILE = os.path.join(data_dir, "state.json")
    cfg.BAL_FILE = os.path.join(data_dir, "balances.json")
    os.makedirs(cfg.BLOCKS_DIR, exist_ok=True)
    os.makedirs(cfg.PENDING_DIR, exist_ok=True)
    return cfg
