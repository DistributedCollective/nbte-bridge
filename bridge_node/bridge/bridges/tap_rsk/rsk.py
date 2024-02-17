import logging
import dataclasses
from pathlib import Path
from typing import NewType

from anemic.ioc import Container, auto, autowired, service
from hexbytes import HexBytes
from sqlalchemy.orm.session import Session
from web3 import Web3
from web3.contract import Contract

from bridge.common.evm.utils import load_abi
from bridge.common.evm.scanner import EvmEventScanner
from bridge.common.services.key_value_store import KeyValueStore
from .common import KEY_VALUE_STORE_NAMESPACE
from .config import Config

logger = logging.getLogger(__name__)
ABI_DIR = Path(__file__).parent / "abi"
BridgeContract = NewType("BridgeContract", Contract)
TapUtilsContract = NewType("TapUtilsContract", Contract)


@service(interface_override=BridgeContract, scope="global")
def create_bridge_contract(container: Container):
    config = container.get(interface=Config)
    web3 = container.get(interface=Web3)
    return web3.eth.contract(
        address=config.evm_bridge_contract_address,
        abi=load_abi("Bridge", abi_dir=ABI_DIR),
    )


@service(interface_override=TapUtilsContract, scope="global")
def create_tap_utils_contract(container: Container):
    web3 = container.get(interface=Web3)
    bridge_contract = container.get(interface=BridgeContract)
    # TODO: this can change, but the factory will always return this address, requiring restart
    tap_utils_address = bridge_contract.functions.tapUtils().call()
    return web3.eth.contract(
        address=tap_utils_address,
        abi=load_abi("TapUtils", abi_dir=ABI_DIR),
    )


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
class RskBridgeService:
    web3: Web3 = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    key_value_store: KeyValueStore = autowired(auto)
    dbsession: Session = autowired(auto)
    config: Config = autowired(auto)

    def __init__(self, container: Container):
        self.container = container
        self.scanner = EvmEventScanner(
            web3=self.web3,
            event=self.bridge_contract.events.TransferToTap,
            callback=self._event_callback,
            dbsession=self.dbsession,
            block_safety_margin=self.config.evm_block_safety_margin,
            key_value_store=self.key_value_store,
            key_value_store_namespace=KEY_VALUE_STORE_NAMESPACE,
            default_start_block=self.config.evm_start_block,
        )

    def scan_new_events(self):
        # TODO: should rather add these to the DB instead of returning
        events = self.scanner.scan_new_events()
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
        return ret

    def _event_callback(self, events):
        logger.info('Event callback: %s', events)
