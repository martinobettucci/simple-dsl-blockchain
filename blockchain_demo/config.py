from dataclasses import dataclass

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
