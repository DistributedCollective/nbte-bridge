import dataclasses
import logging
from anemic.ioc import Container, service, autowired, auto
from hexbytes import HexBytes
from web3 import Web3
from sqlalchemy.orm.session import Session
from .contracts import BridgeContract
from .utils import get_events
from ..services.key_value_store import KeyValueStore
from bridge.config import Config

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TransferToTap:
    sender_evm_address: HexBytes
    recipient_tap_address: str
    #amount_wei: int
    event_tx_hash: HexBytes
    event_block_number: int
    event_block_hash: bytes
    event_tx_index: int
    event_log_index: int


@service(scope="transaction")
class BridgeEventScanner:
    web3: Web3 = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    key_value_store: KeyValueStore = autowired(auto)
    dbsession: Session = autowired(auto)
    config: Config = autowired(auto)

    def __init__(self, container: Container):
        self.container = container

    def scan_events(self):
        # TODO: should rather add these to the DB instead of returning
        last_scanned_block_key = "evm:events:last-scanned-block"
        current_block = self.web3.eth.block_number
        last_scanned_block = self.key_value_store.get_value(
            last_scanned_block_key,
            self.config.evm_start_block,
        )
        from_block = last_scanned_block + 1
        to_block = current_block - self.config.evm_block_safety_margin
        if to_block < from_block:
            logger.info(
                "No new blocks to scan. Last scanned block: %s, current block: %s, margin: %s",
                last_scanned_block,
                current_block,
                self.config.evm_block_safety_margin,
            )
            return []

        logger.info("Scanning events from block %s to block %s", from_block, to_block)

        events = get_events(
            event=self.bridge_contract.events.TransferToTap,
            from_block=from_block,
            to_block=to_block,
        )
        ret = []
        for event in events:
            args = event["args"]
            obj = TransferToTap(
                sender_evm_address=args["from"],
                recipient_tap_address=args["tapAddress"],
                #amount_wei=args["amountWei"],
                event_tx_hash=event["transactionHash"],
                event_block_number=event["blockNumber"],
                event_block_hash=event["blockHash"],
                event_tx_index=event["transactionIndex"],
                event_log_index=event["logIndex"],
            )
            ret.append(obj)

        self.key_value_store.set_value(last_scanned_block_key, to_block)
        return ret
