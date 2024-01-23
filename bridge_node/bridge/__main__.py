import logging
import os

import threading

import bridge
from anemic.ioc import Container, FactoryRegistrySet
from bridge.api.app import create_app
from bridge.core.node import BridgeNode
from bridge.btc.setup import setup_bitcointx_network

logging.basicConfig(level=os.getenv("LOG_LEVEL", logging.INFO))


def main():
    btc_network = os.getenv("BRIDGE_BTC_NETWORK")
    if not btc_network:
        raise RuntimeError("BRIDGE_BTC_NETWORK env variable is not set")
    setup_bitcointx_network(btc_network)

    registries = FactoryRegistrySet()
    global_registry = registries.create_registry("global")
    registries.scan_services(bridge)

    global_container = Container(global_registry)

    threading.Thread(target=create_app, args=(global_container,)).start()

    node = global_container.get(
        interface=BridgeNode,
    )
    node.enter_main_loop()


if __name__ == "__main__":
    main()
