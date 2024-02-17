import logging
from pathlib import Path
from typing import NewType

from anemic.ioc import Container, service
from web3 import Web3
from web3.contract import Contract

from bridge.common.evm.utils import load_abi
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