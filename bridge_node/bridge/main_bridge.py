import logging
import time

from anemic.ioc import Container, auto, autowired, service

from bridge.common.p2p.messaging import MessageEnvelope
from bridge.common.p2p.network import Network
from .bridges.tap_rsk.bridge import TapRskBridge
from .bridges.runes.bridge import RuneBridge
from .common.interfaces.bridge import Bridge
from .config import Config

logger = logging.getLogger(__name__)


@service(scope="global")
class MainBridge(Bridge):
    name = "MAIN_BRIDGE"
    config: Config = autowired(auto)
    network: Network = autowired(auto)
    tap_rsk_bridge: TapRskBridge = autowired(auto)
    rune_bridge: RuneBridge = autowired(auto)

    def __init__(self, container: Container):
        self.container = container
        self.network.add_listener(self.on_message)
        self.enabled_bridge_names = set(self.config.enabled_bridges)
        logger.info("Enabled bridges: %s", self.enabled_bridge_names)

    @property
    def bridges(self) -> list[Bridge]:
        bridges = []
        if "tap_rsk" in self.enabled_bridge_names or "all" in self.enabled_bridge_names:
            bridges.append(self.tap_rsk_bridge)
        if "runesrsk" in self.enabled_bridge_names or "all" in self.enabled_bridge_names:
            bridges.append(self.rune_bridge)
        return bridges

    def init(self):
        for bridge in self.bridges:
            bridge.init()

    def on_message(self, envelope: MessageEnvelope):
        logger.debug("Received message %r from node %s", envelope.message, envelope.sender)

        if envelope.message == "Ping":
            self.network.send(envelope.sender, "Pong")

    def ping(self):
        self.network.broadcast("Ping")

    def enter_main_loop(self):
        while True:
            try:
                self.run_iteration()
            except KeyboardInterrupt:
                break
            except Exception:
                logger.exception("Error in main loop")
            time.sleep(10)

    def run_iteration(self):
        logger.debug("Running main loop iteration from node: %s", self.network.node_id)
        if self.network.is_leader():
            self.ping()
        for bridge in self.bridges:
            try:
                bridge.run_iteration()
            except Exception:
                logger.exception("Error in iteration from bridge %s", bridge.name)
