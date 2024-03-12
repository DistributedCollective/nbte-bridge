import logging

from anemic.ioc import Container, auto, autowired, service
from web3 import Web3

from bridge.common.evm.account import Account
from bridge.common.interfaces.bridge import Bridge
from bridge.common.p2p.network import Network
from bridge.common.services.transactions import TransactionManager
from .faux_service import FauxRuneService

logger = logging.getLogger(__name__)


@service(scope="global")
class RuneBridge(Bridge):
    name = "RUNE_BRIDGE"

    network: Network = autowired(auto)
    transaction_manager: TransactionManager = autowired(auto)
    evm_account: Account = autowired(auto)
    web3: Web3 = autowired(auto)
    faux_service: FauxRuneService = autowired(auto)

    def __init__(self, container: Container):
        self.container = container

    def init(self) -> None:
        return

    def run_iteration(self) -> None:
        if not self.network.is_leader():
            # TODO: right now, only alice will run these
            return

        rune_deposits = self.faux_service.scan_rune_deposits()
        for deposit in rune_deposits:
            self.faux_service.send_rune_to_evm(deposit)

        token_deposits = self.faux_service.scan_token_deposits()
        print("TOKEN DEPOSITS:", token_deposits)
        for deposit in token_deposits:
            self.faux_service.send_token_to_btc(deposit)
