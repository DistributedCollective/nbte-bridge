#!/usr/bin/env python3
import argparse
import getpass
import json
import sys

import config_util as cu


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Encrypt FastBTC config file.")
    parser.add_argument(
        "input",
        metavar="INPUT",
        type=argparse.FileType("r", encoding="utf-8"),
        help="The unencrypted JSON config file (source)",
    )
    parser.add_argument(
        "output",
        metavar="OUTPUT",
        type=argparse.FileType("w", encoding="utf-8"),
        help="The encrypted JSON file (destination)",
    )

    args = parser.parse_args()

    with args.input:
        contents = json.load(args.input)

    if cu.is_encrypted(contents):
        print("Looks like the file is already encrypted!")
        sys.exit(1)

    while True:
        pwd = getpass.getpass("Password: ")
        pwd2 = getpass.getpass("Again: ")
        if pwd2 != pwd:
            print("Passwords do not match")
            continue
        break

    encrypted = cu.encrypt_secrets(pwd.encode(), contents)

    with args.output:
        json.dump(encrypted, args.output, indent=4)
