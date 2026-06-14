import json

from blockchain_demo.transaction import Transaction


def test_canonical_json_is_sorted_and_compact(make_wallet):
    w = make_wallet()
    tx = Transaction(from_addr=w["public_key"], script="let x = x + 1", premium=2, nonce=1)
    cj = tx.canonical_json()
    assert cj == json.dumps(
        {"from": w["public_key"], "script": "let x = x + 1", "premium": 2, "nonce": 1},
        separators=(",", ":"), sort_keys=True,
    )
    # hash is stable
    assert tx.hash() == tx.hash()


def test_signature_valid_then_tamper_rejected(make_wallet):
    w = make_wallet()
    tx = Transaction(from_addr=w["public_key"], script="let x = 1", premium=1, nonce=1)
    tx.sign(w)
    assert tx.verify() is True
    tx.premium = 99  # tamper a signed field
    assert tx.verify() is False


def test_roundtrip_json(make_wallet):
    w = make_wallet()
    tx = Transaction(from_addr=w["public_key"], script="let a = 1", premium=3, nonce=7)
    tx.sign(w)
    tx2 = Transaction.from_json(tx.to_json())
    assert tx2.to_json() == tx.to_json()
    assert tx2.verify() is True
