#!/usr/bin/env python3
import argparse
import getpass
import json
import sys

import config_util as cu


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Decrypt config file.")
    parser.add_argument(
        "input",
        metavar="INPUT",
        type=argparse.FileType("r", encoding="utf-8"),
        help="The encrypted JSON config file (source)",
    )
    parser.add_argument(
        "output",
        metavar="OUTPUT",
        type=argparse.FileType("w", encoding="utf-8"),
        help="The unencrypted JSON file (destination)",
    )

    args = parser.parse_args()

    with args.input:
        contents = json.load(args.input)

    if not cu.is_encrypted(contents):
        print("Looks like the file is not encrypted!")
        sys.exit(1)

    while True:
        pwd = getpass.getpass("Password: ")
        if not pwd:
            print("Give password")
            continue
        break

    decrypted = cu.decrypt_secrets(pwd.encode(), contents)

    with args.output:
        json.dump(decrypted, args.output, indent=4)
