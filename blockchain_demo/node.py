import argparse
import json
import time
from blockchain_demo.config import load_config, CFG


def main():
    parser = argparse.ArgumentParser(description='Demo blockchain node stub')
    parser.add_argument('--config', default='blockchain_demo/config.py')
    parser.add_argument(
        '--local-role', choices=['miner', 'validator', 'both', 'full'], required=True
    )
    parser.add_argument('--wallet', required=True)
    args = parser.parse_args()

    load_config(args.config)

    with open(args.wallet) as f:
        wallet = json.load(f)

    print(f"Starting {args.local_role} node with address {wallet['address']}")
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
