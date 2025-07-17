import json
import os
from typing import List
from .config import CFG
from .wallet import load_wallet
from .transaction import Transaction
from .mempool import Mempool
from .block import Block


class Node:
    def __init__(self, wallet_path: str):
        self.wallet = load_wallet(wallet_path)
        self.mempool = Mempool(CFG.TX_QUEUE_MODE)
        self.chain: List[Block] = []
        self.state = json.load(open('blockchain_demo/state.json'))['state']
        self.balances = json.load(open('blockchain_demo/balances.json'))['balances']

    def submit_tx(self, tx: Transaction):
        if tx.verify():
            self.mempool.add_tx(tx)

    def mine_block(self):
        txs = self.mempool.pop_for_block(CFG.BLOCK_TX_CAP)
        prev_hash = self.chain[-1].hash() if self.chain else '0'*64
        height = len(self.chain)
        block = Block.create_candidate(prev_hash, height, self.wallet['public_key'], txs, self.state, self.balances)
        block.proof_of_work(CFG.DIFFICULTY_BITS)
        self.chain.append(block)
        self.state = block.state
        # simplistic: no validator signatures, immediate finalize
        block.finalized = True
        block.signers_frozen = []
        with open(os.path.join('blockchain_demo/blocks', f"{block.hash()}.json"), 'w') as f:
            json.dump(block.to_json(), f, indent=2)

