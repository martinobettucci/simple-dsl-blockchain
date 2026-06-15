import os
import json

import pytest

from blockchain_demo import network
from blockchain_demo import wallet as wallet_mod
from blockchain_demo.network import PeerInfo

pytestmark = pytest.mark.p0


def test_role_challenge_authenticates_listed_validator(make_wallet, validators):
    vset = [v["public_key"] for v in validators]
    nonce = os.urandom(32).hex()
    v = validators[0]
    sig = wallet_mod.sign(v, nonce)
    # listed validator with a valid signature -> recognized
    assert wallet_mod.verify(v["public_key"], nonce, sig) and v["public_key"] in vset


def test_role_challenge_rejects_unlisted_and_bad_sig(make_wallet, validators):
    vset = [v["public_key"] for v in validators]
    nonce = os.urandom(32).hex()
    outsider = make_wallet("validator")
    sig = wallet_mod.sign(outsider, nonce)
    # valid signature but key not in the validator set
    assert wallet_mod.verify(outsider["public_key"], nonce, sig)
    assert outsider["public_key"] not in vset
    # tampered signature from a real validator
    assert wallet_mod.verify(validators[0]["public_key"], nonce, "00") is False


def test_load_peers_excludes_self(tmp_path):
    p = tmp_path / "peers.json"
    p.write_text(json.dumps({"peers": [
        {"host": "127.0.0.1", "port": 9001},
        {"host": "127.0.0.1", "port": 9002},
    ]}))
    peers = network.load_peers(str(p), self_port=9001)
    assert [pe.port for pe in peers] == [9002]


def test_broadcast_proposal_goes_to_all_peers(monkeypatch):
    # Proposals are broadcast to every peer; each node self-filters and only
    # signs if it is a validator in the parent governance snapshot.  Sending to
    # all (not just already-probed validators) avoids a not-yet-discovered
    # validator unfairly accruing missed-quorum counts while the mesh forms.
    calls = []
    monkeypatch.setattr(network, "_post", lambda peer, path, body, timeout=2.0: calls.append((peer.port, path)))
    p1, p2, p3 = PeerInfo("h", 1), PeerInfo("h", 2), PeerInfo("h", 3)
    p2.is_validator = True
    network.broadcast_block_proposal([p1, p2, p3], {"x": 1})
    assert sorted(calls) == [(1, "/block_proposal"), (2, "/block_proposal"), (3, "/block_proposal")]


def test_broadcast_proposal_fallback_to_all(monkeypatch):
    calls = []
    monkeypatch.setattr(network, "_post", lambda peer, path, body, timeout=2.0: calls.append(peer.port))
    p1, p3 = PeerInfo("h", 1), PeerInfo("h", 3)
    network.broadcast_block_proposal([p1, p3], {"x": 1})
    assert sorted(calls) == [1, 3]
