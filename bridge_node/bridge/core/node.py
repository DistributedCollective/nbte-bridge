import logging
import time
import random

from anemic.ioc import autowired, auto, service, Container

from ..p2p.network import Network
from ..p2p.messaging import MessageEnvelope

logger = logging.getLogger(__name__)


@service(scope="global")
class BridgeNode:
    network: Network = autowired(auto)

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
