"""In-process consensus integration (S-01): 1 miner + 3 validators.

Broadcasts are monkeypatched to deliver synchronously to the peer nodes'
handler methods (the spec's in-memory event bus, §9.4) — no sockets, fully
deterministic.
"""

import os

import pytest

from blockchain_demo import network
from blockchain_demo.network import ChainStore, PeerInfo
from blockchain_demo.node import ChainState
from blockchain_demo.block import Block, BlockHeader, GENESIS_HASH
from blockchain_demo.transaction import Transaction

pytestmark = pytest.mark.p0


def _store(data_dir):
    os.makedirs(os.path.join(data_dir, "blocks"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "pending"), exist_ok=True)
    return ChainStore(
        os.path.join(data_dir, "blocks"), os.path.join(data_dir, "pending"),
        os.path.join(data_dir, "state.json"), os.path.join(data_dir, "balances.json"),
    )


@pytest.fixture
def cluster(cfg_fast, tmp_path, make_wallet, validators, monkeypatch):
    from blockchain_demo.config import governable_dict
    from blockchain_demo.governance import GovernanceState
    miner = make_wallet("miner")
    user = make_wallet("user")
    vset = [v["public_key"] for v in validators]
    g0 = GovernanceState(validators=sorted(vset), config=governable_dict(cfg_fast),
                         miss_counts={v: 0 for v in vset}, last_signed_height={v: 0 for v in vset})
    genesis = Block(BlockHeader(GENESIS_HASH, 0, 0, 0, "genesis"), [],
                    {"counter": 0}, {user["public_key"]: 1000}, finalized=True,
                    governance=g0.to_snapshot())

    specs = [("miner", miner, "miner", 9101),
             ("v1", validators[0], "validator", 9102),
             ("v2", validators[1], "validator", 9103),
             ("v3", validators[2], "validator", 9104)]
    val_ports = {9102, 9103, 9104}
    registry, states = {}, {}
    for name, w, role, port in specs:
        store = _store(os.path.join(tmp_path, name))
        store.save_block(genesis)
        peers = [PeerInfo("127.0.0.1", p) for (_, _, _, p) in specs if p != port]
        st = ChainState(cfg_fast, w, role, port, store, peers)
        registry[port], states[name] = st, st
    for st in states.values():
        for p in st.peers:
            p.is_validator = p.port in val_ports
            p.pubkey = registry[p.port].pubkey

    def route(method):
        def _fn(peers, payload):
            for p in peers:
                getattr(registry[p.port], method)(payload)
        return _fn

    def route_proposal(peers, payload):
        targets = [p for p in peers if p.is_validator] or peers
        for p in targets:
            registry[p.port].on_block_proposal(payload)

    monkeypatch.setattr(network, "broadcast_tx", route("submit_tx"))
    monkeypatch.setattr(network, "broadcast_block_proposal", route_proposal)
    monkeypatch.setattr(network, "broadcast_block_signature", route("on_block_signature"))
    monkeypatch.setattr(network, "broadcast_block_finalized", route("on_block_finalized"))

    return {"states": states, "miner": miner, "user": user, "vset": vset, "cfg": cfg_fast}


def _submit(state, w, script, premium, nonce):
    tx = Transaction(w["public_key"], script, premium, nonce)
    tx.sign(w)
    state.submit_tx(tx.to_json())
    return tx


def test_quorum_finalize_and_convergence(cluster):
    states, user, cfg = cluster["states"], cluster["user"], cluster["cfg"]
    miner_pub = cluster["miner"]["public_key"]

    _submit(states["miner"], user, "let counter = counter + 1", premium=6, nonce=1)
    states["miner"].mine_once()

    # every node converged on the same finalized tip
    tips = {name: st.tip_hash for name, st in states.items()}
    assert len(set(tips.values())) == 1

    tip = states["miner"].chain[-1]
    assert tip.header.height == 1
    assert tip.finalized
    assert tip.state["counter"] == 1
    # quorum freeze: exactly the quorum of signers paid
    from blockchain_demo.block import calc_quorum
    assert len(tip.signers_frozen) >= calc_quorum(len(cluster["vset"]), cfg.QUORUM_PERCENT)
    # miner reward credited
    assert tip.balances[miner_pub] >= cfg.BLOCK_REWARD
    # premium (6) split among the frozen signers
    share = 6 // len(tip.signers_frozen)
    for v in tip.signers_frozen:
        assert tip.balances[v] == share


def test_late_signature_recorded_but_not_paid(cluster):
    states, user = cluster["states"], cluster["user"]
    vset = cluster["vset"]

    _submit(states["miner"], user, "let counter = counter + 1", premium=4, nonce=1)
    states["miner"].mine_once()

    tip = states["miner"].chain[-1]
    bid = tip.hash()
    frozen_before = set(tip.signers_frozen)
    # a validator NOT among the frozen signers sends a late signature
    late = next(v for v in vset if v not in frozen_before)
    late_state = next(s for s in states.values() if s.pubkey == late)
    from blockchain_demo import wallet as wallet_mod
    payload = {"block_hash": bid, "val_pub": late, "sig": wallet_mod.sign(late_state.wallet, bid)}
    states["miner"].on_block_signature(payload)

    updated = states["miner"].blocks[bid]
    assert late in updated.validator_signatures            # recorded for transparency
    assert set(updated.signers_frozen) == frozen_before    # unchanged
    assert updated.balances.get(late, 0) == 0              # not paid


def test_anticensure_premium_ordering(cluster):
    states, user = cluster["states"], cluster["user"]
    # three txs with increasing premium; cap is 3 so all fit in one block,
    # but ordering must be by premium descending
    _submit(states["miner"], user, "let counter = counter + 1", premium=2, nonce=1)
    _submit(states["miner"], user, "let counter = counter + 1", premium=10, nonce=2)
    _submit(states["miner"], user, "let counter = counter + 1", premium=5, nonce=3)
    states["miner"].mine_once()

    tip = states["miner"].chain[-1]
    assert [t.premium for t in tip.transactions] == [10, 5, 2]
