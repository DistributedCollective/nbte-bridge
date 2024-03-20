import logging


from bridge.common.interfaces.bridge import Bridge
from bridge.common.p2p.network import Network
from .service import RuneBridgeService

logger = logging.getLogger(__name__)


class RuneBridge(Bridge):
    def __init__(
        self,
        *,
        bridge_id: str,
        network: Network,
        service: RuneBridgeService,
    ):
        self.bridge_id = bridge_id
        self.name = bridge_id  # Bridge protocol
        self.network = network
        self.service = service

    def init(self) -> None:
        return

    def run_iteration(self) -> None:
        if not self.network.is_leader():
            # TODO: right now, only alice will run these
            return

        rune_deposits = self.service.scan_rune_deposits()
        for deposit in rune_deposits:
            self.service.send_rune_to_evm(deposit)

        token_deposits = self.service.scan_token_deposits()
        for deposit in token_deposits:
            self.service.send_token_to_btc(deposit)
