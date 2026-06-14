import os

import pytest

from blockchain_demo.network import ChainStore
from blockchain_demo.block import block_id, GENESIS_HASH
from tests.helpers import signed_tx, finalized_block

pytestmark = pytest.mark.p0


def _store(tmp_data_dir):
    return ChainStore(
        blocks_dir=os.path.join(tmp_data_dir, "blocks"),
        pending_dir=os.path.join(tmp_data_dir, "pending"),
        state_file=os.path.join(tmp_data_dir, "state.json"),
        bal_file=os.path.join(tmp_data_dir, "balances.json"),
    )


def test_save_load_block_roundtrip(cfg_fast, tmp_data_dir, genesis_block, make_wallet, validators):
    store = _store(tmp_data_dir)
    store.save_block(genesis_block)
    miner = make_wallet("miner")
    vset = [v["public_key"] for v in validators]
    b = finalized_block(cfg_fast, genesis_block, miner, validators, vset, [signed_tx(miner)])
    store.save_block(b)
    loaded = store.load_all_blocks()
    assert set(loaded) == {GENESIS_HASH, block_id(b)}
    assert loaded[block_id(b)].to_json() == b.to_json()


def test_state_and_balances_roundtrip(tmp_data_dir):
    store = _store(tmp_data_dir)
    store.save_state({"counter": 7})
    store.save_balances({"abc": 42})
    assert store.load_state() == {"counter": 7}
    assert store.load_balances() == {"abc": 42}


def test_pending_lifecycle(cfg_fast, tmp_data_dir, genesis_block, make_wallet, validators):
    store = _store(tmp_data_dir)
    miner = make_wallet("miner")
    vset = [v["public_key"] for v in validators]
    b = finalized_block(cfg_fast, genesis_block, miner, validators, vset, [signed_tx(miner)])
    store.save_pending(b)
    assert block_id(b) in store.load_pending()
    store.delete_pending(block_id(b))
    assert block_id(b) not in store.load_pending()


def test_fork_graph_and_longest_chain_wins(cfg_fast, tmp_data_dir, genesis_block, make_wallet, validators):
    store = _store(tmp_data_dir)
    vset = [v["public_key"] for v in validators]
    m1, m2 = make_wallet("miner"), make_wallet("miner")
    blocks = {GENESIS_HASH: genesis_block}
    a1 = finalized_block(cfg_fast, genesis_block, m1, validators, vset, [signed_tx(m1)])
    b1 = finalized_block(cfg_fast, genesis_block, m2, validators, vset,
                         [signed_tx(m2, script="let counter = counter + 5")])
    a2 = finalized_block(cfg_fast, a1, m1, validators, vset, [signed_tx(m1, nonce=2)])
    for blk in (a1, b1, a2):
        blocks[block_id(blk)] = blk

    graph = ChainStore.build_fork_graph(blocks)
    assert set(graph[GENESIS_HASH]) == {block_id(a1), block_id(b1)}
    assert graph[block_id(a1)] == [block_id(a2)]

    chain = store.select_canonical_chain(blocks)
    # branch A (length 3) beats branch B (length 2) regardless of PoW
    assert [block_id(x) for x in chain] == [GENESIS_HASH, block_id(a1), block_id(a2)]


def test_tiebreak_is_deterministic(cfg_fast, tmp_data_dir, genesis_block, make_wallet, validators):
    store = _store(tmp_data_dir)
    vset = [v["public_key"] for v in validators]
    m1, m2 = make_wallet("miner"), make_wallet("miner")
    a1 = finalized_block(cfg_fast, genesis_block, m1, validators, vset, [signed_tx(m1)])
    b1 = finalized_block(cfg_fast, genesis_block, m2, validators, vset,
                         [signed_tx(m2, script="let counter = counter + 9")])
    blocks = {GENESIS_HASH: genesis_block, block_id(a1): a1, block_id(b1): b1}
    chain = store.select_canonical_chain(blocks)
    # equal length (2): winner = higher total PoW, then lexicographically smaller hash
    ranked = sorted(
        (a1, b1),
        key=lambda t: (-(ChainStore.total_pow(genesis_block) + ChainStore.total_pow(t)), block_id(t)),
    )
    assert block_id(chain[-1]) == block_id(ranked[0])


def test_verify_chain_detects_tampering(cfg_fast, genesis_block, make_wallet, validators):
    vset = [v["public_key"] for v in validators]
    m1 = make_wallet("miner")
    a1 = finalized_block(cfg_fast, genesis_block, m1, validators, vset, [signed_tx(m1)])
    assert ChainStore.verify_chain([genesis_block, a1], cfg_fast) is True
    a1.state = {"counter": 999}
    assert ChainStore.verify_chain([genesis_block, a1], cfg_fast) is False
