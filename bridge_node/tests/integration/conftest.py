from typing import cast

import pytest
from web3 import Web3
from web3.types import RPCEndpoint
from eth_account import Account
import pathlib
from eth_typing import ChecksumAddress
from eth_utils import to_hex

from bridge.evm.utils import create_web3, load_abi


WEB3_RPC_URL = "http://localhost:18545"
BRIDGE_CONTRACT_ADDRESS = cast(ChecksumAddress, "0x5FbDB2315678afecb367f032d93F642f64180aa3")
THIS_DIR = pathlib.Path(__file__).parent


@pytest.fixture(scope="session")
def session_web3():
    return Web3(Web3.HTTPProvider(WEB3_RPC_URL))


@pytest.fixture(scope="session", autouse=True)
def integration_test_smoketest(session_web3):
    fail_msg = "Integration test smoketest failed. Check that the docker-compose is running"
    assert session_web3.is_connected(), fail_msg
    assert session_web3.eth.chain_id == 31337, fail_msg
    assert session_web3.eth.block_number > 0, fail_msg


@pytest.fixture()
def user_account(session_web3):
    account = Account.create()
    # Set initial balance for all created accounts
    initial_balance = Web3.to_wei(1, "ether")
    session_web3.provider.make_request(
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
