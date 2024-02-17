from eth_account import Account
from anemic.ioc import service, Container
from bridge.config import Config


@service(interface_override=Account, scope="global")
def create_account(container: Container):
    config = container.get(interface=Config)
    return Account.from_key(config.evm_private_key)
