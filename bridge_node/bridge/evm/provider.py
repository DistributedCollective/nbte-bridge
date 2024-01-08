from web3 import Web3
from web3.middleware import geth_poa_middleware, construct_sign_and_send_raw_middleware
from eth_account import Account
from anemic.ioc import service, Container
from ..config import Config


@service(interface_override=Web3, scope="global")
def create_web3(container: Container):
    config = container.get(interface=Config)
    account = container.get(interface=Account)

    w3 = Web3(Web3.HTTPProvider(config.evm_rpc_url))

    # Fix for this (might not be necessary for all chains):
    # web3.exceptions.ExtraDataLengthError:
    # The field extraData is 97 bytes, but should be 32. It is quite likely that  you are connected to a POA chain.
    # Refer to http://web3py.readthedocs.io/en/stable/middleware.html#geth-style-proof-of-authority for more details.
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    w3.middleware_onion.add(construct_sign_and_send_raw_middleware(account))
    w3.eth.default_account = account.address

    # TODO: gas price strategy (rollup might not support new-style transactions)

    return w3
