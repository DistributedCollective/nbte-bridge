import logging
from collections.abc import Callable

from sqlalchemy.orm.session import Session
from web3 import Web3
from web3.contract.contract import ContractEvent
from web3.types import EventData

from bridge.common.evm.utils import get_events
from bridge.common.services.key_value_store import KeyValueStore

logger = logging.getLogger(__name__)


class EvmEventScanner:
    """
    Generic EVM event scanner
    """

    def __init__(
        self,
        *,
        web3: Web3,
        events: list[ContractEvent],  # TODO: enable scanning all events from contract
        callback: Callable[[list[EventData]], None],
        dbsession: Session,
        block_safety_margin: int,
        key_value_store: KeyValueStore,
        key_value_store_namespace: str,
        default_start_block: int,
    ):
        self._web3 = web3
        self._dbsession = dbsession
        self._block_safety_margin = block_safety_margin
        self._key_value_store = key_value_store
        self._default_start_block = default_start_block
        self._last_scanned_block_key = f"{key_value_store_namespace}:evm:events:last-scanned-block"

        self._events = events
        self._callback = callback

    def scan_new_events(self):
        current_block = self._web3.eth.block_number
        last_scanned_block = self._key_value_store.get_value(
            self._last_scanned_block_key,
            default_value=self._default_start_block,
        )

        from_block = last_scanned_block + 1
        to_block = current_block - self._block_safety_margin
        if to_block < from_block:
            logger.info(
                "No new blocks to scan. Last scanned block: %s, current block: %s, margin: %s",
                last_scanned_block,
                current_block,
                self._block_safety_margin,
            )
            return []

        logger.info("Scanning events from block %s to block %s", from_block, to_block)

        # TODO: this can all be done in one web3 call, no need to query multiple times
        all_event_logs = []
        for event in self._events:
            logger.debug("Fetching events for event: %s", event.event_name)
            event_log_batch = get_events(
                event=event,
                from_block=from_block,
                to_block=to_block,
            )
            all_event_logs.extend(event_log_batch)

        all_event_logs.sort(key=lambda x: (x.blockNumber, x.transactionIndex, x.logIndex))

        self._callback(all_event_logs)

        self._key_value_store.set_value(self._last_scanned_block_key, to_block)
