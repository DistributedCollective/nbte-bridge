from eth_account import Account as EthAccount
from typing import NewType
from anemic.ioc import service, Container
from bridge.config import Config


Account = NewType("Account", EthAccount)


@service(interface_override=Account, scope="global")
def create_account(container: Container):
    config = container.get(interface=Config)
    return EthAccount.from_key(config.evm_private_key)
