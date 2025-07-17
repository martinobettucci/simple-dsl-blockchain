import json
import hashlib
from dataclasses import dataclass
from typing import Dict
from . import wallet


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
        return json.dumps(data, separators=(",", ":"), sort_keys=True)

    def hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

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
