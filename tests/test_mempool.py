from blockchain_demo.mempool import Mempool
from blockchain_demo.transaction import Transaction


def _tx(w, script="let a = 1", premium=1, nonce=1):
    tx = Transaction(from_addr=w["public_key"], script=script, premium=premium, nonce=nonce)
    tx.sign(w)
    return tx


def test_add_tx_checks_signature_nonce_balance(make_wallet):
    w = make_wallet()
    mp = Mempool(balances={w["public_key"]: 5}, mode="premium")
    assert mp.add_tx(_tx(w, premium=2, nonce=1)) is True
    # duplicate hash rejected
    assert mp.add_tx(_tx(w, premium=2, nonce=1)) is False
    # wrong signature
    w2 = make_wallet()
    bad = Transaction(from_addr=w["public_key"], script="let a = 1", premium=2, nonce=2)
    bad.sign(w2)
    assert mp.add_tx(bad) is False
    # insufficient balance
    assert mp.add_tx(_tx(w, premium=10, nonce=2)) is False
    # non-monotonic nonce
    assert mp.add_tx(_tx(w, premium=1, nonce=1)) is False


def test_cumulative_premium_reservation(make_wallet):
    w = make_wallet()
    mp = Mempool(balances={w["public_key"]: 5}, mode="premium")
    assert mp.add_tx(_tx(w, premium=3, nonce=1)) is True
    # 3 reserved, 5 balance -> a second premium of 3 would exceed (3+3 > 5)
    assert mp.add_tx(_tx(w, premium=3, nonce=2)) is False
    # but a premium of 2 fits exactly (3+2 == 5)
    assert mp.add_tx(_tx(w, premium=2, nonce=2)) is True


def test_pop_releases_reservation(make_wallet):
    w = make_wallet()
    mp = Mempool(balances={w["public_key"]: 5}, mode="premium")
    assert mp.add_tx(_tx(w, premium=5, nonce=1)) is True
    mp.pop_for_block(1)
    # reservation released -> can add again (new higher nonce)
    assert mp.add_tx(_tx(w, premium=5, nonce=2)) is True


def test_premium_ordering(make_wallet):
    w1, w2, w3 = make_wallet(), make_wallet(), make_wallet()
    bal = {w["public_key"]: 100 for w in (w1, w2, w3)}
    mp = Mempool(balances=bal, mode="premium")
    mp.add_tx(_tx(w1, premium=2, nonce=1))
    mp.add_tx(_tx(w2, premium=10, nonce=1))
    mp.add_tx(_tx(w3, premium=2, nonce=1))
    ordered = mp.pop_for_block(3)
    # highest premium first; ties keep arrival order (w1 before w3)
    assert [t.premium for t in ordered] == [10, 2, 2]
    assert ordered[1].from_addr == w1["public_key"]


def test_fifo_ordering(make_wallet):
    w1, w2 = make_wallet(), make_wallet()
    bal = {w["public_key"]: 100 for w in (w1, w2)}
    mp = Mempool(balances=bal, mode="fifo")
    mp.add_tx(_tx(w1, premium=1, nonce=1))
    mp.add_tx(_tx(w2, premium=5, nonce=1))
    ordered = mp.pop_for_block(2)
    assert [t.premium for t in ordered] == [1, 5]


def test_requeue_reinserts(make_wallet):
    w = make_wallet()
    mp = Mempool(balances={w["public_key"]: 100}, mode="premium")
    tx = _tx(w, premium=4, nonce=1)
    mp.add_tx(tx)
    popped = mp.pop_for_block(1)
    assert len(mp) == 0
    mp.requeue(popped)
    assert len(mp) == 1
    assert mp.pop_for_block(1)[0].hash() == tx.hash()
