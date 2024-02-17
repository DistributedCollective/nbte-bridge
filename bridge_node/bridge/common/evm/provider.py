from anemic.ioc import Container, service
from eth_account import Account
from web3 import Web3

from .utils import create_web3
from bridge.config import Config


@service(interface_override=Web3, scope="global")
def web3_factory(container: Container):
    config = container.get(interface=Config)
    account = container.get(interface=Account)

    return create_web3(config.evm_rpc_url, account=account)
