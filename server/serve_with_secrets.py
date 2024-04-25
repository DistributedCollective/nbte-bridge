#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import time

from getpass import getpass

import config_util as cu


def decrypt_secrets_file(path):
    with open(path) as f:
        contents = json.load(f)

        if cu.is_encrypted(contents):
            tries = 0

            while True:
                try:
                    pwd = getpass(f"Password for decrypting {path}: ")
                    contents = cu.decrypt_secrets(pwd.encode(), contents)
                    break
                except Exception as e:
                    tries += 1
                    print(f"Error decrypting secrets: {e}.")

                    if tries >= 3:
                        exit(1)

                    print("Please try again.")

        return contents


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Start bridge nodes and send decrypted config to them."
    )
    parser.add_argument(
        "compose",
        metavar="COMPOSE_FILE",
        type=str,
        help="The docker compose file to use for starting the bridge nodes.",
    )

    args = parser.parse_args()

    node = "bridge-node"

    # Get config file name from input
    config_file = input(f"Path to config file for {node}: ")

    config = json.dumps(decrypt_secrets_file(config_file), indent=None)

    compose_up = subprocess.run(
        ["docker", "compose", "-f", args.compose, "up", "-d", "--build"],
        stdout=sys.stdout,
    )

    if not compose_up.returncode == 0:
        print("Error starting bridge nodes")
        exit(1)

    proc = subprocess.Popen(
        ["docker", "compose", "-f", args.compose, "attach", node],
        stdin=subprocess.PIPE,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"Sending config to {node}...")

    time.sleep(2)

    proc.stdin.write(config + "\n")
    proc.stdin.flush()

    time.sleep(2)

    proc.kill()

    print("Done.")
