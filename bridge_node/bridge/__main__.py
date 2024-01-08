import os
import logging
import socket

import bridge
from bridge.core.node import BridgeNode
from bridge.p2p.network import Network, PyroNetwork

from anemic.ioc import Container, FactoryRegistrySet

logging.basicConfig(level=os.getenv("LOG_LEVEL", logging.INFO))


def main():
    node_id = os.getenv("BRIDGE_NODE_ID", None)
    hostname = os.getenv("BRIDGE_HOSTNAME", socket.gethostname())

    def create_pyro_network(_):
        network = PyroNetwork(
            node_id=node_id,
            host=hostname,
            port=5000,
        )
        import time

        # TODO: VERY UGLY! But we don't want to crash on startup if network not started
        # Should rather start the daemon outside of __init__ and then only broadcast after it's started
        time.sleep(2)

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
