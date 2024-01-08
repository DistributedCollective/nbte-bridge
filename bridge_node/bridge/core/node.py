import logging
import time

from anemic.ioc import autowired, auto, Container

from ..p2p.network import Network

logger = logging.getLogger(__name__)


class BridgeNode:
    network: Network = autowired(auto)

    def __init__(self, container: Container):
        self.container = container
        self.network.add_listener(self.on_message)

    def on_message(self, msg):
        logger.debug("Received message to node: %s", msg)

        if msg == "Ping":
            self.network.broadcast("Pong")

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
        self.ping()
