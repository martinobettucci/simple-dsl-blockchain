import os
from blockchain_demo.mempool import Mempool
from blockchain_demo.transaction import Transaction
from blockchain_demo import wallet


def create_wallet(tmp_path):
    path = os.path.join(tmp_path, 'w.json')
    return wallet.generate_wallet(path, local_role='user')


def test_add_tx_checks_signature_nonce_balance(tmp_path):
    w = create_wallet(tmp_path)
    balances = {w['public_key']: 5}
    mp = Mempool(balances=balances, mode='premium')
    tx = Transaction(from_addr=w['public_key'], script='let x=1', premium=2, nonce=1)
    tx.sign(w)
    assert mp.add_tx(tx) is True
    # duplicate hash rejected
    assert mp.add_tx(tx) is False
    # wrong signature
    w2 = create_wallet(tmp_path)
    tx2 = Transaction(from_addr=w['public_key'], script='let x=1', premium=2, nonce=2)
    tx2.sign(w2)
    assert mp.add_tx(tx2) is False
    # low balance
    tx3 = Transaction(from_addr=w['public_key'], script='let x=1', premium=10, nonce=2)
    tx3.sign(w)
    assert mp.add_tx(tx3) is False
    # nonce not monotonic
    tx4 = Transaction(from_addr=w['public_key'], script='let x=1', premium=1, nonce=1)
    tx4.sign(w)
    assert mp.add_tx(tx4) is False


def test_queue_modes(tmp_path):
    w1 = create_wallet(tmp_path)
    w2 = create_wallet(tmp_path)
    balances = {w1['public_key']: 100, w2['public_key']: 100}
    # premium mode
    mp = Mempool(balances=balances, mode='premium')
    tx1 = Transaction(from_addr=w1['public_key'], script='let a=1', premium=1, nonce=1)
    tx1.sign(w1)
    mp.add_tx(tx1)
    tx2 = Transaction(from_addr=w2['public_key'], script='let a=1', premium=5, nonce=1)
    tx2.sign(w2)
    mp.add_tx(tx2)
    ordered = mp.pop_for_block(2)
    assert [t.premium for t in ordered] == [5, 1]
    # fifo mode
    mp2 = Mempool(balances=balances, mode='fifo')
    tx3 = Transaction(from_addr=w1['public_key'], script='let a=1', premium=1, nonce=1)
    tx3.sign(w1)
    mp2.add_tx(tx3)
    tx4 = Transaction(from_addr=w2['public_key'], script='let a=1', premium=5, nonce=1)
    tx4.sign(w2)
    mp2.add_tx(tx4)
    ordered2 = mp2.pop_for_block(2)
    assert [t.premium for t in ordered2] == [1, 5]

