"""ECDSA wallets (SECP256k1) with deterministic signatures.

Signatures use RFC6979 deterministic nonces and an explicit SHA-256 hash
function.  python-ecdsa otherwise defaults to SHA-1 and a *random* nonce, which
is both weak and non-reproducible — bad for a teaching tool and for tests.  Sign
and verify must use the same hash function, which they do here.

A wallet is a plain JSON dict::

    {
      "public_key": hex,   # SECP256k1 point, used as the address
      "private_key": hex,
      "address": hex,      # == public_key (spec §21: pubkey hex)
      "last_nonce": int,   # last nonce used by this wallet when sending tx
      "local_role": str    # miner / validator / both / full / user
    }
"""

import json
import hashlib
from typing import Dict, Optional

from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError

_HASH = hashlib.sha256


def generate_wallet(path: str, local_role: str = "miner") -> Dict:
    sk = SigningKey.generate(curve=SECP256k1)
    vk = sk.verifying_key
    pub = vk.to_string().hex()
    data = {
        "public_key": pub,
        "private_key": sk.to_string().hex(),
        "address": pub,
        "last_nonce": 0,
        "local_role": local_role,
    }
    save_wallet(path, data)
    return data


def load_wallet(path: str) -> Dict:
    with open(path) as f:
        data = json.load(f)
    if "private_key" not in data or "public_key" not in data:
        raise ValueError(f"Invalid wallet file: {path}")
    return data


def save_wallet(path: str, data: Dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def sign(wallet: Dict, message: str) -> str:
    """Deterministically sign ``message`` with the wallet's private key."""
    sk = SigningKey.from_string(bytes.fromhex(wallet["private_key"]), curve=SECP256k1)
    return sk.sign_deterministic(message.encode(), hashfunc=_HASH).hex()


def verify(pubkey: str, message: str, signature: str) -> bool:
    """Verify ``signature`` of ``message`` against ``pubkey`` (all hex)."""
    if not signature:
        return False
    try:
        vk = VerifyingKey.from_string(bytes.fromhex(pubkey), curve=SECP256k1)
        return vk.verify(bytes.fromhex(signature), message.encode(), hashfunc=_HASH)
    except (BadSignatureError, ValueError):
        return False
    except Exception:
        return False


def next_nonce(wallet: Dict, path: Optional[str] = None) -> int:
    """Return the next nonce (last_nonce + 1), persisting it if ``path`` given.

    Nonces must be strictly increasing per address (mempool rejects
    ``nonce <= last_seen``), so a sender must bump and persist this between
    transactions.
    """
    nonce = int(wallet.get("last_nonce", 0)) + 1
    wallet["last_nonce"] = nonce
    if path is not None:
        save_wallet(path, wallet)
    return nonce
