import os
import logging

import bridge
from bridge.core.node import BridgeNode
from bridge.p2p.network import Network, PyroNetwork

from anemic.ioc import Container, FactoryRegistrySet

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

    registries = FactoryRegistrySet()
    global_registry = registries.create_registry("global")
    global_registry.register(
        interface=Network,
        factory=create_pyro_network,
    )
    registries.scan_services(bridge)

    global_container = Container(global_registry)
    node = global_container.get(
        interface=BridgeNode,
    )
    node.enter_main_loop()


if __name__ == "__main__":
    main()
