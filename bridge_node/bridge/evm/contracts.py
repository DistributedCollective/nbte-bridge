from typing import NewType
from web3 import Web3
from web3.contract import Contract
from anemic.ioc import service, Container
from .utils import load_abi
from ..config import Config


BridgeContract = NewType("BridgeContract", Contract)


@service(interface_override=BridgeContract, scope="global")
def create_bridge_contract(container: Container):
    config = container.get(interface=Config)
    web3 = container.get(interface=Web3)
    return web3.eth.contract(
        address=config.evm_bridge_contract_address,
        abi=load_abi("Bridge"),
    )
