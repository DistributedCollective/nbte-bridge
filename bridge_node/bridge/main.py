import logging
import os
import threading

from anemic.ioc import Container, FactoryRegistrySet

import bridge
from bridge.api.app import create_app
from bridge.common.btc.setup import setup_bitcointx_network
from bridge.common.services.transactions import register_transaction_manager
from bridge.decimalcontext import set_decimal_context
from bridge.main_bridge import MainBridge

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", logging.INFO),
    format="%(asctime)s:%(name)s:%(levelname)s:%(message)s",
)


def main():
    set_decimal_context()
    btc_network = os.getenv("BRIDGE_BTC_NETWORK")
    if not btc_network:
        raise RuntimeError("BRIDGE_BTC_NETWORK env variable is not set")
    setup_bitcointx_network(btc_network)

    registries = FactoryRegistrySet()
    global_registry = registries.create_registry("global")
    transaction_registry = registries.create_registry("transaction")
    registries.scan_services(bridge)

    register_transaction_manager(
        global_registry=global_registry,
        transaction_registry=transaction_registry,
    )

    global_container = Container(global_registry)

    threading.Thread(target=create_app, args=(global_container,)).start()

    main_bridge = global_container.get(
        interface=MainBridge,
    )
    main_bridge.init()
    main_bridge.enter_main_loop()
