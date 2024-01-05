import os

from bridge.core.node import BridgeNode
from bridge.p2p.network import P2PNetwork


def main():
    node_id = os.getenv("BRIDGE_NODE_ID", None)

    network = P2PNetwork(node_id, "0.0.0.0", 5000)  # Careful. Only use this when running in Docker.
    BridgeNode(network)

    network.start()
    network.broadcast(f"{network.uri} joined the network")


if __name__ == "__main__":
    main()
