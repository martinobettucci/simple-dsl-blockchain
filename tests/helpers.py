"""Shared test builders."""

from blockchain_demo.block import Block, block_id
from blockchain_demo.transaction import Transaction
from blockchain_demo import wallet as wallet_mod


def signed_tx(w, script="let counter = counter + 1", premium=2, nonce=1):
    tx = Transaction(from_addr=w["public_key"], script=script, premium=premium, nonce=nonce)
    tx.sign(w)
    return tx


def finalized_block(cfg, parent, miner, validators, vset, txs=(), num_signers=2):
    """Build, mine, sign (num_signers validators) and finalize a child block."""
    b = Block.create_candidate(
        block_id(parent), parent.header.height + 1, miner["public_key"],
        list(txs), parent.state, parent.balances, cfg,
    )
    b.proof_of_work(cfg.DIFFICULTY_BITS)
    for v in validators[:num_signers]:
        b.add_validator_signature(v["public_key"], wallet_mod.sign(v, b.hash()), vset)
    b.finalize(vset, parent.balances, cfg)
    return b
