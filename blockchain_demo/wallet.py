import os
import json
from dataclasses import dataclass
from ecdsa import SigningKey, VerifyingKey, SECP256k1


def generate_wallet(path: str, local_role: str = "miner"):
    sk = SigningKey.generate(curve=SECP256k1)
    vk = sk.verifying_key
    data = {
        "public_key": vk.to_string().hex(),
        "private_key": sk.to_string().hex(),
        "address": vk.to_string().hex(),
        "last_nonce": 0,
        "local_role": local_role,
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    return data


def load_wallet(path: str):
    with open(path) as f:
        return json.load(f)


def sign(wallet, message: str) -> str:
    sk = SigningKey.from_string(bytes.fromhex(wallet['private_key']), curve=SECP256k1)
    return sk.sign(message.encode()).hex()


def verify(pubkey: str, message: str, signature: str) -> bool:
    try:
        vk = VerifyingKey.from_string(bytes.fromhex(pubkey), curve=SECP256k1)
        return vk.verify(bytes.fromhex(signature), message.encode())
    except Exception:
        return False
