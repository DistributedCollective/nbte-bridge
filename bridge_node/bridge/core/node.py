import logging
import time
import random

from anemic.ioc import autowired, auto, service, Container

from ..p2p.network import Network
from ..p2p.messaging import MessageEnvelope

from ..evm.scanner import BridgeEventScanner, TransferToBTC

logger = logging.getLogger(__name__)


@service(scope="global")
class BridgeNode:
    network: Network = autowired(auto)
    evm_scanner: BridgeEventScanner = autowired(auto)

    def __init__(self, container: Container):
        self.container = container
        self.network.add_listener(self.on_message)

    def on_message(self, envelope: MessageEnvelope):
        logger.debug("Received message %r from node %s", envelope.message, envelope.sender)

        if envelope.message == "Ping":
            self.network.send(envelope.sender, "Pong")

    def ping(self):
        self.network.broadcast("Ping")

    def enter_main_loop(self):
        while True:
            try:
                self._run_iteration()
            except KeyboardInterrupt:
                break
            except Exception:
                logger.exception("Error in main loop")
            time.sleep(10)

    def _run_iteration(self):
        logger.debug("Running main loop iteration from node: %s", self.network.node_id)
        if not random.randint(0, 3):
            # Randomly ping nodes to demonstrate network connectivity
            self.ping()
        events = self.evm_scanner.scan_events()
        for event in events:
            match event:
                case TransferToBTC():
                    for _ in range(5):
                        logger.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                    logger.info(
                        "Found transfer to BTC: %s",
                        event,
                    )
                case _:
                    logger.info("Found unknown event: %s", event)
