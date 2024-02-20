import logging

from anemic.ioc import Container, auto, autowired, service
from web3 import Web3

from bridge.common.evm.account import Account
from bridge.common.interfaces.bridge import Bridge
from bridge.common.p2p.network import Network
from bridge.common.services.transactions import TransactionManager
from bridge.common.tap.client import TapRestClient
from .rsk import BridgeContract
from .rsk_scanner import RskEventScanner
from .rsk_to_tap import RskToTapService
from .tap_deposits import TapDepositService
from .tap_to_rsk import TapToRskService

logger = logging.getLogger(__name__)


@service(scope="global")
class TapRskBridge(Bridge):
    name = "TAP_RSK_BRIDGE"

    network: Network = autowired(auto)
    transaction_manager: TransactionManager = autowired(auto)
    evm_account: Account = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    web3: Web3 = autowired(auto)
    tap_client: TapRestClient = autowired(auto)
    rsk_to_tap: RskToTapService = autowired(auto)
    tap_to_rsk: TapToRskService = autowired(auto)

    def __init__(self, container: Container):
        self.container = container

    def init(self):
        self.rsk_to_tap.init()
        self.tap_to_rsk.init()

    def run_iteration(self):
        logger.debug("Running TAP-EVM bridge iteration from node: %s", self.network.node_id)

        with self.transaction_manager.transaction() as transaction:
            rsk_scanner = transaction.find_service(RskEventScanner)
            tap_deposit_service = transaction.find_service(TapDepositService)

            rsk_scanner.scan_new_events()
            tap_deposit_service.scan_new_deposits()

        if not self.network.is_leader():
            logger.info("Not leader, not doing anything")
            return

        try:
            self.rsk_to_tap.process_current_transfer_batch()
        except Exception:
            logger.exception("Error processing RSK to TAP transfers")
        try:
            self.tap_to_rsk.process_current_transfer_batch()
        except Exception:
            logger.exception("Error processing TAP to RSK transfers")
