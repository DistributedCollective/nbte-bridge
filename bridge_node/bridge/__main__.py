import logging
import os

import threading

import bridge
from anemic.ioc import Container, FactoryRegistrySet
from bridge.api.app import create_app
from bridge.core.node import BridgeNode
from bridge.btc.monkeypatch import BitcoinTxMonkeyPatcher

logging.basicConfig(level=os.getenv("LOG_LEVEL", logging.INFO))


def main():
    registries = FactoryRegistrySet()
    global_registry = registries.create_registry("global")
    registries.scan_services(bridge)

    global_container = Container(global_registry)

    monkeypatch_bitcointx = global_container.get(interface=BitcoinTxMonkeyPatcher)
    monkeypatch_bitcointx()

    # Start after monkeybatching bitcointx
    threading.Thread(target=create_app).start()

    node = global_container.get(
        interface=BridgeNode,
    )
    node.enter_main_loop()


if __name__ == "__main__":
    main()
