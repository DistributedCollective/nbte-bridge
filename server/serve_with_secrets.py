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
            pwd = getpass(f"Password for decrypting {path}: ")

            try:
                contents = cu.decrypt_secrets(pwd.encode(), contents)
            except Exception as e:
                print(f"Error decrypting secrets: {e}")
                exit(1)

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

    compose_up = subprocess.run(
        ["docker", "compose", "-f", args.compose, "up", "-d", "--build"],
        stdout=sys.stdout,
    )

    if not compose_up.returncode == 0:
        print("Error starting bridge nodes")
        exit(1)

    for node in ["bridge-node-1", "bridge-node-2", "bridge-node-3"]:
        # Get config file name from input
        config_file = input(f"Path to config file for {node}: ")

        config = json.dumps(decrypt_secrets_file(config_file), indent=None)

        proc = subprocess.Popen(
            ["docker", "compose", "-f", args.compose, "attach", node],
            stdin=subprocess.PIPE,
            text=True,
        )
        print(f"Sending config {config} to {node}...")
        proc.stdin.write(config + "\n")
        time.sleep(2)
        proc.terminate()
        print("Done.")
