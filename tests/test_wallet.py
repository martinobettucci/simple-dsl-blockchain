import os

from blockchain_demo import wallet as wallet_mod


def test_generate_and_keys_differ(tmp_path):
    w = wallet_mod.generate_wallet(os.path.join(tmp_path, "w.json"), local_role="miner")
    assert w["public_key"] != w["private_key"]
    assert w["address"] == w["public_key"]
    assert w["local_role"] == "miner"
    # SECP256k1: 32-byte priv, 64-byte pub -> hex lengths
    assert len(w["private_key"]) == 64
    assert len(w["public_key"]) == 128


def test_sign_verify_roundtrip(make_wallet):
    w = make_wallet()
    sig = wallet_mod.sign(w, "hello world")
    assert wallet_mod.verify(w["public_key"], "hello world", sig) is True


def test_sign_is_deterministic(make_wallet):
    # RFC6979 -> signing the same message twice yields identical bytes
    w = make_wallet()
    assert wallet_mod.sign(w, "abc") == wallet_mod.sign(w, "abc")


def test_tampered_message_fails(make_wallet):
    w = make_wallet()
    sig = wallet_mod.sign(w, "payload")
    assert wallet_mod.verify(w["public_key"], "payload-tampered", sig) is False


def test_wrong_key_fails(make_wallet):
    w1, w2 = make_wallet(), make_wallet()
    sig = wallet_mod.sign(w1, "msg")
    assert wallet_mod.verify(w2["public_key"], "msg", sig) is False


def test_empty_signature_fails(make_wallet):
    w = make_wallet()
    assert wallet_mod.verify(w["public_key"], "msg", "") is False


def test_next_nonce_persists(tmp_path):
    path = os.path.join(tmp_path, "w.json")
    w = wallet_mod.generate_wallet(path, local_role="user")
    assert wallet_mod.next_nonce(w, path) == 1
    assert wallet_mod.next_nonce(w, path) == 2
    reloaded = wallet_mod.load_wallet(path)
    assert reloaded["last_nonce"] == 2
