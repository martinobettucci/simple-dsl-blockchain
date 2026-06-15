"""Transaction model: signed payload + premium + nonce.

A transaction carries a ``type`` (default ``"dsl"``).  DSL transactions mutate
the global ``state`` via their ``script``; governance transactions
(``validator_apply``/``validator_vote``/``config_propose``/``config_vote``) carry
a ``data`` payload and never touch ``state`` (see ``governance.py``).

Canonical JSON (UTF-8, sorted keys, compact separators) is the single source of
truth for both the hash (§10.3) and the signed payload (§10.2).  For legacy DSL
transactions (``type=="dsl"`` and empty ``data``) the canonical form is the
original four-key object, so their hashes and signatures stay byte-identical.
"""

import json
import hashlib
from dataclasses import dataclass, field
from typing import Dict

from . import wallet


@dataclass
class Transaction:
    from_addr: str
    script: str
    premium: int
    nonce: int
    signature: str = ""
    type: str = "dsl"
    data: Dict = field(default_factory=dict)

    def canonical_json(self) -> str:
        """Deterministic JSON of the signed fields (no signature)."""
        payload = {
            "from": self.from_addr,
            "script": self.script,
            "premium": self.premium,
            "nonce": self.nonce,
        }
        # Governance / non-default txs include type+data; legacy DSL txs keep the
        # original four-key form so existing hashes and signatures are preserved.
        if self.type != "dsl" or self.data:
            payload["type"] = self.type
            payload["data"] = self.data
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    def hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    def sign(self, wallet_data: Dict) -> "Transaction":
        self.signature = wallet.sign(wallet_data, self.canonical_json())
        return self

    def verify(self) -> bool:
        return wallet.verify(self.from_addr, self.canonical_json(), self.signature)

    def to_json(self) -> Dict:
        return {
            "from": self.from_addr,
            "script": self.script,
            "premium": self.premium,
            "nonce": self.nonce,
            "signature": self.signature,
            "type": self.type,
            "data": self.data,
        }

    @classmethod
    def from_json(cls, data: Dict) -> "Transaction":
        return cls(
            from_addr=data["from"],
            script=data.get("script", ""),
            premium=int(data["premium"]),
            nonce=int(data["nonce"]),
            signature=data.get("signature", ""),
            type=data.get("type", "dsl"),
            data=data.get("data", {}) or {},
        )

