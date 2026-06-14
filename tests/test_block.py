import pytest

from blockchain_demo.block import Block, GENESIS_HASH, calc_quorum
from blockchain_demo.transaction import Transaction
from blockchain_demo import wallet as wallet_mod

pytestmark = pytest.mark.p0


def _tx(w, script="let counter = counter + 1", premium=2, nonce=1):
    tx = Transaction(from_addr=w["public_key"], script=script, premium=premium, nonce=nonce)
    tx.sign(w)
    return tx


def _candidate(cfg, miner, txs, parent_balances, state=None):
    b = Block.create_candidate(
        GENESIS_HASH, 1, miner["public_key"], txs,
        state or {"counter": 0}, parent_balances, cfg,
    )
    b.proof_of_work(cfg.DIFFICULTY_BITS)
    return b


def _sign(block, validators, vset, n):
    for v in validators[:n]:
        block.add_validator_signature(v["public_key"], wallet_mod.sign(v, block.hash()), vset)


def test_calc_quorum():
    assert calc_quorum(3, 51) == 2
    assert calc_quorum(5, 80) == 4
    assert calc_quorum(4, 100) == 4
    assert calc_quorum(1, 51) == 1


def test_canonical_dict_excludes_balances(cfg_fast, make_wallet):
    w = make_wallet("miner")
    b = _candidate(cfg_fast, w, [_tx(w)], {w["public_key"]: 0})
    assert "balances" not in b.canonical_dict()
    assert set(b.canonical_dict().keys()) == {"header", "transactions", "state"}


def test_hash_stable_across_signatures_and_finalize(cfg_fast, make_wallet, validators):
    miner = make_wallet("miner")
    vset = [v["public_key"] for v in validators]
    pb = {miner["public_key"]: 0}
    b = _candidate(cfg_fast, miner, [_tx(miner)], pb)
    h = b.hash()
    _sign(b, validators, vset, 2)
    assert b.hash() == h  # signatures excluded from identity
    b.finalize(vset, pb, cfg_fast)
    assert b.hash() == h  # finalize rewrites balances but not identity


def test_pow_meets_target_and_mutation_fails(cfg_fast, make_wallet):
    w = make_wallet("miner")
    b = _candidate(cfg_fast, w, [_tx(w)], {w["public_key"]: 0})
    assert b.has_valid_pow(cfg_fast.DIFFICULTY_BITS)
    b.state = {"counter": 999999}
    assert not b.has_valid_pow(cfg_fast.DIFFICULTY_BITS)


def test_from_json_roundtrip(cfg_fast, make_wallet, validators):
    miner = make_wallet("miner")
    vset = [v["public_key"] for v in validators]
    pb = {miner["public_key"]: 0}
    b = _candidate(cfg_fast, miner, [_tx(miner)], pb)
    _sign(b, validators, vset, 2)
    b.finalize(vset, pb, cfg_fast)
    b2 = Block.from_json(b.to_json())
    assert b2.to_json() == b.to_json()
    assert b2.hash() == b.hash()


def test_finalize_distributes_rewards(cfg_fast, make_wallet, validators):
    miner = make_wallet("miner")
    user = make_wallet("user")
    vset = [v["public_key"] for v in validators]
    pb = {user["public_key"]: 100, miner["public_key"]: 0, vset[0]: 0, vset[1]: 0, vset[2]: 0}
    txs = [_tx(user, premium=4, nonce=1),
           _tx(user, script="let counter = counter + 2", premium=3, nonce=2)]
    b = _candidate(cfg_fast, miner, txs, pb)
    _sign(b, validators, vset, 2)
    b.finalize(vset, pb, cfg_fast)
    # total premiums = 7, 2 signers -> share 3 each, remainder 1 -> miner
    assert b.signers_frozen == sorted([vset[0], vset[1]])
    assert b.balances[vset[0]] == 3
    assert b.balances[vset[1]] == 3
    assert b.balances[miner["public_key"]] == cfg_fast.BLOCK_REWARD + 1
    assert b.balances[vset[2]] == 0          # non-signer paid nothing
    assert b.balances[user["public_key"]] == 100 - 7  # sender debited the premiums
    # conservation: only BLOCK_REWARD is newly minted (remainder -> miner)
    assert sum(b.balances.values()) - sum(pb.values()) == cfg_fast.BLOCK_REWARD


def test_late_signature_recorded_but_not_paid(cfg_fast, make_wallet, validators):
    miner = make_wallet("miner")
    user = make_wallet("user")
    vset = [v["public_key"] for v in validators]
    pb = {user["public_key"]: 100}
    b = _candidate(cfg_fast, miner, [_tx(user, premium=6, nonce=1)], pb)
    _sign(b, validators, vset, 2)
    b.finalize(vset, pb, cfg_fast)
    frozen, bal_before = list(b.signers_frozen), dict(b.balances)
    late = validators[2]
    assert b.add_validator_signature(late["public_key"], wallet_mod.sign(late, b.hash()), vset) is True
    b.finalize(vset, pb, cfg_fast)  # idempotent
    assert late["public_key"] in b.validator_signatures  # visible for transparency
    assert b.signers_frozen == frozen                    # unchanged
    assert b.balances == bal_before                       # not paid


def test_finalize_quorum_not_reached(cfg_fast, make_wallet, validators):
    miner = make_wallet("miner")
    vset = [v["public_key"] for v in validators]
    b = _candidate(cfg_fast, miner, [], {miner["public_key"]: 0})
    _sign(b, validators, vset, 1)  # only one signature, quorum is 2
    with pytest.raises(ValueError):
        b.finalize(vset, {}, cfg_fast)


def test_signature_rejects_non_validator_and_bad_sig(cfg_fast, make_wallet, validators):
    miner = make_wallet("miner")
    vset = [v["public_key"] for v in validators]
    outsider = make_wallet("validator")
    b = _candidate(cfg_fast, miner, [], {miner["public_key"]: 0})
    assert b.add_validator_signature(
        outsider["public_key"], wallet_mod.sign(outsider, b.hash()), vset) is False
    assert b.add_validator_signature(validators[0]["public_key"], "deadbeef", vset) is False
