import os
import logging

from bridge.core.node import BridgeNode
from bridge.p2p.network import PyroNetwork

logging.basicConfig(level=os.getenv("LOG_LEVEL", logging.INFO))


def main():
    node_id = os.getenv("BRIDGE_NODE_ID", None)

    network = PyroNetwork(
        node_id=node_id,
        host="0.0.0.0",
        port=5000,
    )  # Careful. Only use this hostname when running in Docker.

    BridgeNode(network)

    network.broadcast(f"{network.uri} joined the network")


if __name__ == "__main__":
    main()
