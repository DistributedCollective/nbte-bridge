import logging

from anemic.ioc import Container, auto, autowired, service
from sqlalchemy.orm.session import Session
from web3 import Web3
from web3.types import EventData

from bridge.common.evm.scanner import EvmEventScanner
from bridge.common.services.key_value_store import KeyValueStore
from .common import KEY_VALUE_STORE_NAMESPACE
from .config import Config
from .models import RskToTapTransfer
from .rsk import BridgeContract

logger = logging.getLogger(__name__)


@service(scope="transaction")
class RskEventScanner:
    web3: Web3 = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    key_value_store: KeyValueStore = autowired(auto)
    dbsession: Session = autowired(auto)
    config: Config = autowired(auto)

    def __init__(self, container: Container):
        self.container = container

    def scan_new_events(self):
        """
        Scan events and add to DB
        """
        scanner = EvmEventScanner(
            web3=self.web3,
            events=[
                self.bridge_contract.events.TransferToTap,
            ],
            callback=self._scan_events_callback,
            dbsession=self.dbsession,
            block_safety_margin=self.config.evm_block_safety_margin,
            key_value_store=self.key_value_store,
            key_value_store_namespace=KEY_VALUE_STORE_NAMESPACE,
            default_start_block=self.config.evm_start_block,
        )
        scanner.scan_new_events()

    def _scan_events_callback(self, events: list[EventData]):
        logger.info('Event callback: %s', events)
        for event in events:
            if event['event'] == 'TransferToTap':
                instance = RskToTapTransfer(
                    counter=event["args"]['counter'],
                    sender_rsk_address=event["args"]["from"],
                    recipient_tap_address=event["args"]["tapAddress"],
                    rsk_event_tx_hash=event["transactionHash"].hex(),
                    rsk_event_block_number=event["blockNumber"],
                    rsk_event_tx_index=event["transactionIndex"],
                    rsk_event_log_index=event["logIndex"],
                )
                self.dbsession.add(instance)
                self.dbsession.flush()
            else:
                logger.warning('Unknown event: %s', event)
        self.dbsession.flush()
