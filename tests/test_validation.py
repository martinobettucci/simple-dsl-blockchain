import os
import sys
import tempfile
import hashlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from blockchain_demo import wallet
from blockchain_demo.transaction import Transaction
from blockchain_demo.mempool import Mempool
from blockchain_demo.config import Config


def create_wallet():
    td = tempfile.TemporaryDirectory()
    path = os.path.join(td.name, 'w.json')
    wallet.generate_wallet(path)
    return wallet.load_wallet(path)


def sign_tx(tx, w):
    tx.sign(w)
    return tx


def test_premium_validation():
    w = create_wallet()
    cfg = Config(MIN_PREMIUM=5)
    tx = Transaction(from_addr=w['public_key'], script='let a=1', premium=1, nonce=1)
    sign_tx(tx, w)
    assert not tx.is_premium_valid(cfg)
    mp = Mempool(balances={w['public_key']: 10}, mode='premium', cfg=cfg)
    mp.nonces[w['public_key']] = 0
    assert not mp.add_tx(tx)


def test_nonce_monotonicity():
    w = create_wallet()
    tx = Transaction(from_addr=w['public_key'], script='let a=1', premium=1, nonce=1)
    sign_tx(tx, w)
    assert not tx.is_nonce_valid(1)
    mp = Mempool(balances={w['public_key']: 10})
    mp.nonces[w['public_key']] = 1
    assert not mp.add_tx(tx)


def test_balance_validation():
    w = create_wallet()
    tx = Transaction(from_addr=w['public_key'], script='let a=1', premium=10, nonce=1)
    sign_tx(tx, w)
    assert not tx.has_sufficient_balance({w['public_key']: 5})
    mp = Mempool(balances={w['public_key']: 5})
    mp.nonces[w['public_key']] = 0
    assert not mp.add_tx(tx)


def test_canonical_hash():
    w = create_wallet()
    tx = Transaction(from_addr=w['public_key'], script='let x=1', premium=2, nonce=3)
    sign_tx(tx, w)
    from blockchain_demo.utils import canonical_bytes
    h1 = tx.hash()
    h2 = hashlib.sha256(canonical_bytes({
        "from": w['public_key'],
        "script": 'let x=1',
        "premium": 2,
        "nonce": 3,
    })).hexdigest()
    assert h1 == h2

