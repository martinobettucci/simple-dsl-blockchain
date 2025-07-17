import argparse
import json
import time


def main():
    parser = argparse.ArgumentParser(description='Demo blockchain node stub')
    parser.add_argument('--role', choices=['miner', 'validator'], required=True)
    parser.add_argument('--wallet', required=True)
    args = parser.parse_args()

    with open(args.wallet) as f:
        wallet = json.load(f)

    print(f"Starting {args.role} node with address {wallet['address']}")
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
