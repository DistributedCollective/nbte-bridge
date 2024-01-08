import dataclasses
import logging
from anemic.ioc import Container, service, autowired, auto
from hexbytes import HexBytes
from web3 import Web3
from .contracts import BridgeContract
from .utils import get_events


logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TransferToBTC:
    sender_evm_address: HexBytes
    recipient_btc_address: str
    amount_wei: int
    event_tx_hash: HexBytes
    event_block_number: int
    event_block_hash: bytes
    event_tx_index: int
    event_log_index: int


@service(scope="global")
class BridgeEventScanner:
    web3: Web3 = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    _last_scanned_block = 0
    block_safety_margin = 5  # TODO: make configurable

    def __init__(self, container: Container):
        self.container = container

    def scan_events(self):
        # TODO: should rather add these to the DB instead of returning
        current_block = self.web3.eth.block_number
        from_block = self._last_scanned_block + 1
        to_block = current_block - self.block_safety_margin
        if to_block < from_block:
            logger.info(
                "No new blocks to scan. Last scanned block: %s, current block: %s, margin: %s",
                self._last_scanned_block,
                current_block,
                self.block_safety_margin,
            )
            return []

        logger.info("Scanning events from block %s to block %s", from_block, to_block)

        events = get_events(
            event=self.bridge_contract.events.TransferToBTC,
            from_block=from_block,
            to_block=to_block,
        )
        ret = []
        for event in events:
            args = event["args"]
            obj = TransferToBTC(
                sender_evm_address=args["from"],
                recipient_btc_address=args["btcAddress"],
                amount_wei=args["amountWei"],
                event_tx_hash=event["transactionHash"],
                event_block_number=event["blockNumber"],
                event_block_hash=event["blockHash"],
                event_tx_index=event["transactionIndex"],
                event_log_index=event["logIndex"],
            )
            ret.append(obj)

        self._last_scanned_block = to_block
        return ret
