import json
import hashlib
from dataclasses import dataclass
from typing import Dict
from . import wallet, dsl
from .config import CFG
from .utils import canonical_bytes


@dataclass
class Transaction:
    from_addr: str
    script: str
    premium: int
    nonce: int
    signature: str = ""

    def canonical_json(self) -> str:
        data = {
            "from": self.from_addr,
            "script": self.script,
            "premium": self.premium,
            "nonce": self.nonce,
        }
        return canonical_bytes(data).decode()

    def hash(self) -> str:
        return hashlib.sha256(canonical_bytes({
            "from": self.from_addr,
            "script": self.script,
            "premium": self.premium,
            "nonce": self.nonce,
        })).hexdigest()

    def sign(self, wallet_data: Dict[str, str]):
        self.signature = wallet.sign(wallet_data, self.canonical_json())

    def verify(self) -> bool:
        return wallet.verify(self.from_addr, self.canonical_json(), self.signature)

    def to_json(self) -> Dict:
        return {
            "from": self.from_addr,
            "script": self.script,
            "premium": self.premium,
            "nonce": self.nonce,
            "signature": self.signature,
        }

    @classmethod
    def from_json(cls, data: Dict):
        return cls(
            from_addr=data["from"],
            script=data["script"],
            premium=data["premium"],
            nonce=data["nonce"],
            signature=data.get("signature", ""),
        )

    # Validation helpers -------------------------------------------------
    def is_premium_valid(self, cfg=CFG) -> bool:
        """Check if premium meets minimum requirement."""
        return self.premium >= cfg.MIN_PREMIUM

    def is_nonce_valid(self, last_nonce: int) -> bool:
        """Check if nonce is strictly greater than last known nonce."""
        return self.nonce > last_nonce

    def has_sufficient_balance(self, balances: Dict[str, int]) -> bool:
        """Check if sender balance covers the premium."""
        return balances.get(self.from_addr, 0) >= self.premium

    def validate(self, balances: Dict[str, int], last_nonce: int, cfg=CFG) -> bool:
        """Full validation according to specifications."""
        if not self.verify():
            return False
        if not self.is_premium_valid(cfg):
            return False
        if not self.is_nonce_valid(last_nonce):
            return False
        if not self.has_sufficient_balance(balances):
            return False
        try:
            dsl.parse_script(self.script)
        except Exception:
            return False
        return True
