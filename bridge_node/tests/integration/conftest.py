from typing import cast

import pytest
from eth_account import Account
from eth_utils import to_hex
from web3 import Web3
from web3.types import RPCEndpoint

from bridge.btc.setup import setup_bitcointx_network
from bridge.btc.rpc import BitcoinRPC
from bridge.evm.utils import create_web3, load_abi
from .constants import (
    BRIDGE_CONTRACT_ADDRESS,
    MULTISIG_BITCOIN_RPC_URL,
    USER_BITCOIN_RPC_URL,
    WEB3_RPC_URL,
)

setup_bitcointx_network("regtest")  # it's a global variable, just like Satoshi intended


@pytest.fixture(scope="session")
def web3():
    return Web3(Web3.HTTPProvider(WEB3_RPC_URL))


@pytest.fixture(scope="session")
def user_bitcoin_rpc():
    return BitcoinRPC(USER_BITCOIN_RPC_URL)


@pytest.fixture(scope="session")
def multisig_bitcoin_rpc():
    return BitcoinRPC(MULTISIG_BITCOIN_RPC_URL)


@pytest.fixture(scope="session", autouse=True)
def integration_test_smoketest(web3, user_bitcoin_rpc, multisig_bitcoin_rpc):
    fail_msg = "Integration test smoketest failed. Check that the docker-compose is running"
    assert web3.is_connected(), fail_msg
    assert web3.eth.chain_id == 31337, fail_msg
    assert web3.eth.block_number > 0, fail_msg
    assert user_bitcoin_rpc.getblockcount() > 0, "Bitcoind is not running or not mining blocks"
    assert multisig_bitcoin_rpc.getblockcount() > 0, "Bitcoind is not running or not mining blocks"


@pytest.fixture()
def user_account(web3):
    account = Account.create()
    # Set initial balance for all created accounts
    initial_balance = Web3.to_wei(1, "ether")
    web3.provider.make_request(
        cast(RPCEndpoint, "hardhat_setBalance"),
        [account.address, to_hex(initial_balance)],
    )
    return account


@pytest.fixture()
def user_web3(user_account) -> Web3:
    return create_web3(WEB3_RPC_URL, account=user_account)


@pytest.fixture()
def user_bridge_contract(user_web3):
    return user_web3.eth.contract(
        address=BRIDGE_CONTRACT_ADDRESS,
        abi=load_abi("Bridge"),
    )
