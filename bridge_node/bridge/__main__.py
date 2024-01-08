import os
import logging

from bridge.core.node import BridgeNode
from bridge.p2p.network import Network, PyroNetwork

from anemic.ioc import Container, FactoryRegistry

logging.basicConfig(level=os.getenv("LOG_LEVEL", logging.INFO))


def main():
    node_id = os.getenv("BRIDGE_NODE_ID", None)

    def create_pyro_network(_):
        network = PyroNetwork(
            node_id=node_id,
            host="0.0.0.0",
            port=5000,
        )  # Careful. Only use this hostname when running in Docker.
        network.broadcast(f"{network.uri} joined the network")
        return network

    global_registry = FactoryRegistry("global")
    global_registry.register(
        interface=Network,
        factory=create_pyro_network,
    )
    global_registry.register(
        interface=BridgeNode,
        factory=BridgeNode,
    )

    global_container = Container(global_registry)
    node = global_container.get(
        interface=BridgeNode,
    )
    node.enter_main_loop()


if __name__ == "__main__":
    main()
