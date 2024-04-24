import logging
import time

from anemic.ioc import Container, auto, autowired, service

from bridge.common.p2p.network import Network

from .bridges.runes.bridge import RuneBridge
from .bridges.tap_rsk.bridge import TapRskBridge
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
        self.enabled_bridge_names = set(self.config.enabled_bridges)
        logger.info("Enabled bridges: %s", self.enabled_bridge_names)
        self._pong_nonce = 0

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
        self.network.answer_with("main:ping", self._answer_pong)

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

    def ping(self):
        # self.network.broadcast("Ping")
        answers = self.network.ask("main:ping", nonce=self._pong_nonce)
        self._pong_nonce += 1
        for answer in answers:
            logger.debug(
                "Received pong to nonce %d from node %s",
                answer["nonce"],
                answer["sender"],
            )
        logger.info(
            "Node: %s; Is leader?: %s; Nodes online: %d",
            self.network.node_id,
            self.network.is_leader(),
            len(answers) + 1,
        )

    def _answer_pong(self, nonce: int):
        return {"message": "pong", "nonce": nonce, "sender": self.network.node_id}
