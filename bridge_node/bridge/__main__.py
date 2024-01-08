import logging
import os

import bridge
from anemic.ioc import Container, FactoryRegistrySet
from bridge.core.node import BridgeNode

logging.basicConfig(level=os.getenv("LOG_LEVEL", logging.INFO))


def main():
    registries = FactoryRegistrySet()
    global_registry = registries.create_registry("global")
    registries.scan_services(bridge)

    global_container = Container(global_registry)
    node = global_container.get(
        interface=BridgeNode,
    )
    node.enter_main_loop()


if __name__ == "__main__":
    main()
