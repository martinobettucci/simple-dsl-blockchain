import os
import json
from blockchain_demo.wallet import generate_wallet
from blockchain_demo.block import Block, BlockHeader
from blockchain_demo.config import CFG


def main():
    os.makedirs('wallets', exist_ok=True)
    validators = []
    balances = {}
    for idx, name in enumerate(["Val-A", "Val-B", "Val-C"], start=1):
        path = os.path.join('wallets', f'validator{idx}.json')
        wallet_data = generate_wallet(path, local_role='validator')
        validators.append({"pubkey": wallet_data["public_key"], "name": name})
        balances[wallet_data["public_key"]] = 100

    validators_json = {"validators": validators, "quorum_percent": CFG.QUORUM_PERCENT}
    with open(os.path.join('blockchain_demo', 'validators.json'), 'w') as f:
        json.dump(validators_json, f, indent=2)

    state = {"counter": 0}
    with open(os.path.join('blockchain_demo', 'state.json'), 'w') as f:
        json.dump({"state": state}, f, indent=2)
    with open(os.path.join('blockchain_demo', 'balances.json'), 'w') as f:
        json.dump({"balances": balances}, f, indent=2)

    header = BlockHeader(prev_hash='0'*64, height=0, nonce=0, timestamp=0, miner='genesis')
    genesis_block = Block(
        header=header,
        transactions=[],
        state=state,
        balances=balances,
        finalized=True,
        validator_signatures={},
        signers_frozen=[],
    )
    genesis_json = genesis_block.to_json()
    genesis_json["hash"] = '0'*64
    os.makedirs(os.path.join('blockchain_demo', 'blocks'), exist_ok=True)
    with open(os.path.join('blockchain_demo', 'blocks', '0000000000000000000000000000000000000000000000000000000000000000.json'), 'w') as f:
        json.dump(genesis_json, f, indent=2)


if __name__ == '__main__':
    main()
