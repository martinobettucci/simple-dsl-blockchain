import os
import json
import requests
import time
from typing import List
from .wallet import verify


class PeerInfo:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.pubkey = None
        self.is_validator = False
        self.last_seen = 0
        self.latency_ms = 0.0

    @property
    def url(self):
        return f"http://{self.host}:{self.port}"


def probe_peer(peer: PeerInfo, validator_set: List[str]):
    start = time.time()
    try:
        r = requests.get(peer.url + "/status", timeout=2)
        status = r.json()
        pubkey_claim = status.get("pubkey")
    except Exception:
        return
    latency = (time.time() - start) * 1000
    nonce = os.urandom(32).hex()
    try:
        r = requests.post(peer.url + "/role_challenge", json={"nonce": nonce, "expect_validator": True}, timeout=2)
        resp = r.json()
    except Exception:
        return
    pubkey = resp.get("pubkey", pubkey_claim)
    sig = resp.get("signature")
    if sig and verify(pubkey, nonce, sig) and pubkey in validator_set:
        peer.is_validator = True
    peer.pubkey = pubkey
    peer.last_seen = time.time()
    peer.latency_ms = latency

