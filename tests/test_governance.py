import pytest

from blockchain_demo.config import Config, governable_dict
from blockchain_demo.governance import GovernanceState, apply_block, quorum_at, genesis_state
from blockchain_demo.block import Block, BlockHeader, GENESIS_HASH
from blockchain_demo.transaction import Transaction

pytestmark = pytest.mark.p0


def gov_cfg(**over):
    params = {"QUORUM_PERCENT": 51, "LIVENESS_OFFLINE_N": 3, "LIVENESS_MISS_X": 2, "VALIDATOR_FLOOR": 1}
    params.update(over)
    return governable_dict(Config(**params))


def make_G0(vpubs, **cfg_over):
    vs = sorted(vpubs)
    return GovernanceState(validators=vs, config=gov_cfg(**cfg_over),
                           miss_counts={v: 0 for v in vs}, last_signed_height={v: 0 for v in vs})


def gtx(addr, type_, data=None, nonce=1):
    return Transaction(from_addr=addr, script="", premium=0, nonce=nonce, type=type_, data=data or {})


def blk(height, txs=(), signers=()):
    return Block(header=BlockHeader(prev_hash="p" * 64, height=height, nonce=0, timestamp=0, miner="m"),
                 transactions=list(txs), state={}, balances={}, signers_frozen=list(signers))


@pytest.fixture
def vpubs(make_wallet):
    return [make_wallet("validator")["public_key"] for _ in range(3)]


def test_genesis_state_roundtrip(vpubs):
    g0 = make_G0(vpubs)
    genesis = Block(BlockHeader(GENESIS_HASH, 0, 0, 0, "genesis"), [], {}, {},
                    finalized=True, governance=g0.to_snapshot())
    assert sorted(genesis_state(genesis).validators) == sorted(vpubs)


def test_admission_at_quorum(vpubs, make_wallet):
    g0 = make_G0(vpubs)
    cand = make_wallet("validator")["public_key"]
    b = blk(1, [gtx(cand, "validator_apply"),
               gtx(vpubs[0], "validator_vote", {"candidate": cand}),
               gtx(vpubs[1], "validator_vote", {"candidate": cand})], signers=vpubs)
    g1 = apply_block(g0, b, height=1)
    assert cand not in g0.validators
    assert cand in g1.validators


def test_admission_below_quorum(vpubs, make_wallet):
    g0 = make_G0(vpubs)
    cand = make_wallet("validator")["public_key"]
    b = blk(1, [gtx(cand, "validator_apply"),
               gtx(vpubs[0], "validator_vote", {"candidate": cand})], signers=vpubs)
    assert cand not in apply_block(g0, b, height=1).validators


def test_votes_from_non_validators_ignored(vpubs, make_wallet):
    g0 = make_G0(vpubs)
    cand = make_wallet("validator")["public_key"]
    outsider = make_wallet("validator")["public_key"]
    b = blk(1, [gtx(cand, "validator_apply"),
               gtx(cand, "validator_vote", {"candidate": cand}),       # self-vote, not a validator
               gtx(outsider, "validator_vote", {"candidate": cand})],  # outsider, not a validator
            signers=vpubs)
    assert cand not in apply_block(g0, b, height=1).validators


def test_timing_quorum_increases_next_block(vpubs, make_wallet):
    g0 = make_G0(vpubs)
    cand = make_wallet("validator")["public_key"]
    b = blk(1, [gtx(cand, "validator_apply"),
               gtx(vpubs[0], "validator_vote", {"candidate": cand}),
               gtx(vpubs[1], "validator_vote", {"candidate": cand})], signers=vpubs)
    g1 = apply_block(g0, b, height=1)
    assert quorum_at(g0) == 2   # ceil(3*51/100)
    assert quorum_at(g1) == 3   # ceil(4*51/100) -> the new validator counts next block


def test_admitted_validator_not_charged_miss(vpubs, make_wallet):
    g0 = make_G0(vpubs)
    cand = make_wallet("validator")["public_key"]
    b = blk(1, [gtx(cand, "validator_apply"),
               gtx(vpubs[0], "validator_vote", {"candidate": cand}),
               gtx(vpubs[1], "validator_vote", {"candidate": cand})], signers=vpubs)  # cand can't sign yet
    g1 = apply_block(g0, b, height=1)
    assert g1.miss_counts[cand] == 0
    assert g1.last_signed_height[cand] == 1


def test_auto_removal_offline_after_N(vpubs):
    g0 = make_G0(vpubs, LIVENESS_OFFLINE_N=3, LIVENESS_MISS_X=100)
    offline = vpubs[2]
    others = [v for v in vpubs if v != offline]
    g = g0
    for h in range(1, 4):  # blocks 1..3: offline never signs, but h - 0 not > 3 yet
        g = apply_block(g, blk(h, signers=others), height=h)
    assert offline in g.validators
    g = apply_block(g, blk(4, signers=others), height=4)  # 4 - 0 > 3 -> removed
    assert offline not in g.validators


def test_auto_removal_cumulative_misses(vpubs):
    g0 = make_G0(vpubs, LIVENESS_OFFLINE_N=100, LIVENESS_MISS_X=2)
    offline = vpubs[2]
    others = [v for v in vpubs if v != offline]
    g1 = apply_block(g0, blk(1, signers=others), height=1)
    assert offline in g1.validators            # miss=1 < 2
    g2 = apply_block(g1, blk(2, signers=others), height=2)
    assert offline not in g2.validators        # miss=2 >= 2 -> removed


def test_removed_validator_can_reapply(vpubs):
    g0 = make_G0(vpubs, LIVENESS_OFFLINE_N=100, LIVENESS_MISS_X=1)
    offline = vpubs[2]
    others = [v for v in vpubs if v != offline]
    g1 = apply_block(g0, blk(1, signers=others), height=1)
    assert offline not in g1.validators        # removed (miss 1 >= 1)
    # re-apply + votes from the two remaining validators (quorum of 2 = 2)
    b = blk(2, [gtx(offline, "validator_apply"),
               gtx(others[0], "validator_vote", {"candidate": offline}),
               gtx(others[1], "validator_vote", {"candidate": offline})], signers=others)
    g2 = apply_block(g1, b, height=2)
    assert offline in g2.validators


def test_config_change_activates_at_quorum(vpubs):
    g0 = make_G0(vpubs)
    propose = gtx(vpubs[0], "config_propose", {"changes": {"DIFFICULTY_BITS": 6}})
    pid = propose.hash()
    b = blk(1, [propose, gtx(vpubs[1], "config_vote", {"pid": pid})], signers=vpubs)
    g1 = apply_block(g0, b, height=1)
    assert g0.config["DIFFICULTY_BITS"] != 6
    assert g1.config["DIFFICULTY_BITS"] == 6


def test_config_change_ignores_non_governable_keys(vpubs):
    g0 = make_G0(vpubs)
    propose = gtx(vpubs[0], "config_propose", {"changes": {"API_PORT": 1, "DIFFICULTY_BITS": 7}})
    pid = propose.hash()
    b = blk(1, [propose, gtx(vpubs[1], "config_vote", {"pid": pid})], signers=vpubs)
    g1 = apply_block(g0, b, height=1)
    assert "API_PORT" not in g1.config
    assert g1.config["DIFFICULTY_BITS"] == 7


def test_safety_floor_prevents_emptying(vpubs):
    g0 = make_G0(vpubs, LIVENESS_MISS_X=1, LIVENESS_OFFLINE_N=100, VALIDATOR_FLOOR=2)
    g1 = apply_block(g0, blk(1, signers=[]), height=1)  # all 3 miss -> all removable
    assert len(g1.validators) == 2                      # floor stops removal at 2


def test_fold_is_deterministic(vpubs, make_wallet):
    g0 = make_G0(vpubs)
    cand = make_wallet("validator")["public_key"]
    txs = [gtx(cand, "validator_apply"),
           gtx(vpubs[0], "validator_vote", {"candidate": cand}),
           gtx(vpubs[1], "validator_vote", {"candidate": cand})]
    s1 = apply_block(g0, blk(1, txs, signers=vpubs), height=1).to_snapshot()
    s2 = apply_block(g0, blk(1, txs, signers=vpubs), height=1).to_snapshot()
    assert s1 == s2
