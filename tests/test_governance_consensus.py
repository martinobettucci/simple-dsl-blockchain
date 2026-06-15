"""In-process governance consensus: vote a 4th validator in, auto-remove an
offline one.  Broadcasts are monkeypatched to a synchronous in-memory bus (no
sockets), exactly like ``test_consensus_flow``."""

import os

import pytest

from blockchain_demo import network
from blockchain_demo.network import ChainStore, PeerInfo
from blockchain_demo.node import ChainState
from blockchain_demo.block import Block, BlockHeader, GENESIS_HASH, calc_quorum
from blockchain_demo.transaction import Transaction
from blockchain_demo.config import Config, governable_dict
from blockchain_demo.governance import GovernanceState

pytestmark = pytest.mark.p0


def _store(data_dir):
    os.makedirs(os.path.join(data_dir, "blocks"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "pending"), exist_ok=True)
    return ChainStore(os.path.join(data_dir, "blocks"), os.path.join(data_dir, "pending"),
                      os.path.join(data_dir, "state.json"), os.path.join(data_dir, "balances.json"))


def _genesis(vset, cfg, balances=None):
    g0 = GovernanceState(validators=sorted(vset), config=governable_dict(cfg),
                         miss_counts={v: 0 for v in vset}, last_signed_height={v: 0 for v in vset})
    return Block(BlockHeader(GENESIS_HASH, 0, 0, 0, "genesis"), [], {"counter": 0},
                 dict(balances or {}), finalized=True, governance=g0.to_snapshot())


def _gtx(w, type_, data, nonce):
    return Transaction(w["public_key"], "", 0, nonce, type=type_, data=data).sign(w)


def _dsl(w, nonce):
    return Transaction(w["public_key"], "let counter = counter + 1", 0, nonce).sign(w)


def build_cluster(monkeypatch, cfg, tmp_path, miner, validators, candidate=None):
    vset = [v["public_key"] for v in validators]
    genesis = _genesis(vset, cfg)
    specs = [("miner", miner, "miner", 9201),
             ("v1", validators[0], "validator", 9202),
             ("v2", validators[1], "validator", 9203),
             ("v3", validators[2], "validator", 9204)]
    if candidate:
        specs.append(("cand", candidate, "validator", 9205))
    ports = [p for *_, p in specs]
    registry, states = {}, {}
    for name, w, role, port in specs:
        store = _store(os.path.join(tmp_path, name))
        store.save_block(genesis)
        peers = [PeerInfo("127.0.0.1", p) for p in ports if p != port]
        st = ChainState(cfg, w, role, port, store, peers)
        registry[port], states[name] = st, st

    val_ports = {9202, 9203, 9204}  # the initial validators (genesis set)
    for st in states.values():
        for p in st.peers:
            p.pubkey = registry[p.port].pubkey
            p.is_validator = p.port in val_ports

    offline = set()

    def route(method):
        def _fn(peers, payload):
            for p in peers:
                if p.port in offline:
                    continue
                getattr(registry[p.port], method)(payload)
        return _fn

    monkeypatch.setattr(network, "broadcast_tx", route("submit_tx"))
    monkeypatch.setattr(network, "broadcast_block_proposal", route("on_block_proposal"))
    monkeypatch.setattr(network, "broadcast_block_signature", route("on_block_signature"))
    monkeypatch.setattr(network, "broadcast_block_finalized", route("on_block_finalized"))
    return states, registry, offline


def test_vote_in_fourth_validator(cfg_fast, tmp_path, make_wallet, validators, monkeypatch):
    miner = make_wallet("miner")
    candidate = make_wallet("validator")
    states, _, _ = build_cluster(monkeypatch, cfg_fast, tmp_path, miner, validators, candidate)
    cand_pub = candidate["public_key"]

    # candidate applies; two existing validators vote for it
    states["cand"].submit_tx(_gtx(candidate, "validator_apply", {}, 1).to_json())
    states["v1"].submit_tx(_gtx(validators[0], "validator_vote", {"candidate": cand_pub}, 1).to_json())
    states["v2"].submit_tx(_gtx(validators[1], "validator_vote", {"candidate": cand_pub}, 1).to_json())

    states["miner"].mine_once()  # one block carries the three governance txs

    tip = states["miner"].chain[-1]
    assert tip.finalized and tip.header.height == 1
    assert cand_pub in tip.governance["validators"]                       # admitted
    assert tip.governance["quorum"] == calc_quorum(4, cfg_fast.QUORUM_PERCENT)  # 2 -> 3
    assert len({s.tip_hash for s in states.values()}) == 1               # all converged

    # the new validator is now part of the set governing the NEXT block: its
    # signature over a later block is accepted (height-dependent membership)
    states["miner"].submit_tx(_dsl(make_wallet("user"), 1).to_json())
    states["miner"].mine_once()
    b2 = states["miner"].chain[-1]
    assert b2.header.height == 2
    from blockchain_demo import wallet as wallet_mod
    res = states["miner"].on_block_signature(
        {"block_hash": b2.hash(), "val_pub": cand_pub,
         "sig": wallet_mod.sign(candidate, b2.hash())})
    assert cand_pub in states["miner"].blocks[b2.hash()].validator_signatures
    assert res["status"] == "ok"


def test_online_validators_not_starved_beyond_quorum(tmp_path, make_wallet, validators, monkeypatch):
    # Regression: with a signature-gathering grace window the proposer waits for
    # all online validators, so a healthy validator beyond the bare quorum is
    # still credited every block and never accrues a spurious missed-quorum count
    # (otherwise a 3-validator / quorum-2 chain would auto-remove its "extra"
    # validator down to the floor).
    cfg = Config(DIFFICULTY_BITS=8, QUORUM_PERCENT=51, BLOCK_REWARD=5, BLOCK_TX_CAP=3,
                 MIN_PREMIUM=0, TX_QUEUE_MODE="premium", PREMIUM_REMAINDER_TARGET="miner",
                 LIVENESS_MISS_X=2, LIVENESS_OFFLINE_N=100, VALIDATOR_FLOOR=1, SIGNATURE_GRACE=5.0)
    miner = make_wallet("miner")
    user = make_wallet("user")
    states, _, _ = build_cluster(monkeypatch, cfg, tmp_path, miner, validators)
    vset = {v["public_key"] for v in validators}

    for nonce in (1, 2, 3):
        states["miner"].submit_tx(_dsl(user, nonce).to_json())
        states["miner"].mine_once()

    tip = states["miner"].chain[-1]
    assert tip.header.height == 3
    for b in states["miner"].chain[1:]:
        assert set(b.signers_frozen) == vset          # all three credited every block
    assert set(tip.governance["validators"]) == vset  # nobody auto-removed
    assert all(c == 0 for c in tip.governance["miss_counts"].values())


def test_offline_validator_auto_removed(tmp_path, make_wallet, validators, monkeypatch):
    cfg = Config(DIFFICULTY_BITS=8, QUORUM_PERCENT=51, BLOCK_REWARD=5, BLOCK_TX_CAP=3,
                 MIN_PREMIUM=0, TX_QUEUE_MODE="premium", PREMIUM_REMAINDER_TARGET="miner",
                 LIVENESS_MISS_X=2, LIVENESS_OFFLINE_N=100, VALIDATOR_FLOOR=1)
    miner = make_wallet("miner")
    user = make_wallet("user")
    states, _, offline = build_cluster(monkeypatch, cfg, tmp_path, miner, validators)
    v3 = validators[2]["public_key"]
    offline.add(9204)  # v3 stops participating

    for nonce in (1, 2):
        states["miner"].submit_tx(_dsl(user, nonce).to_json())
        states["miner"].mine_once()

    tip = states["miner"].chain[-1]
    assert tip.header.height == 2
    assert v3 not in tip.governance["validators"]      # auto-removed after MISS_X misses
    assert set(tip.governance["validators"]) == {validators[0]["public_key"],
                                                 validators[1]["public_key"]}
