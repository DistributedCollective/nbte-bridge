import pathlib
from typing import cast

import pytest
from eth_account import Account
from eth_utils import to_hex
from web3 import Web3
from web3.types import RPCEndpoint

from bridge.api_client import BridgeAPIClient
from bridge.bridges.tap_rsk.rsk import ABI_DIR
from bridge.common.btc.rpc import BitcoinRPC
from bridge.common.btc.setup import setup_bitcointx_network
from bridge.common.evm.utils import create_web3, load_abi
from bridge.common.tap.client import TapRestClient

from .constants import (
    ALICE_EVM_PRIVATE_KEY,
    BRIDGE_CONTRACT_ADDRESS,
    NODE1_API_BASE_URL,
    PROJECT_BASE_DIR,
    USER_BITCOIN_RPC_URL,
    WEB3_RPC_URL,
)

# we need the fixtures from other modules to be available automatically, so let's import them
from .fixtures.harness import harness  # noqa

MACAROON_SUBPATH = pathlib.Path("data") / "regtest" / "admin.macaroon"

setup_bitcointx_network("regtest")  # it's a global variable, just like Satoshi intended


@pytest.fixture(scope="session")
def web3():
    return Web3(Web3.HTTPProvider(WEB3_RPC_URL))


@pytest.fixture(scope="session")
def bitcoin_rpc():
    return BitcoinRPC(USER_BITCOIN_RPC_URL)


@pytest.fixture(scope="session")
def alice_tap():
    base_dir = PROJECT_BASE_DIR / "volumes" / "tapd" / "alice-tap"
    return TapRestClient(
        public_universe_host="alice-tap",
        rest_host="localhost:8289",
        macaroon_path=base_dir / MACAROON_SUBPATH,
        tls_cert_path=base_dir / "tls.cert",
    )


@pytest.fixture(scope="session")
def bob_tap():
    base_dir = PROJECT_BASE_DIR / "volumes" / "tapd" / "bob-tap"
    return TapRestClient(
        rest_host="localhost:8290",
        macaroon_path=base_dir / MACAROON_SUBPATH,
        tls_cert_path=base_dir / "tls.cert",
    )


@pytest.fixture(scope="session")
def carol_tap():
    base_dir = PROJECT_BASE_DIR / "volumes" / "tapd" / "carol-tap"
    return TapRestClient(
        rest_host="localhost:8291",
        macaroon_path=base_dir / MACAROON_SUBPATH,
        tls_cert_path=base_dir / "tls.cert",
    )


@pytest.fixture(scope="session")
def user_tap():
    base_dir = PROJECT_BASE_DIR / "volumes" / "tapd" / "user-tap"
    return TapRestClient(
        rest_host="localhost:8292",
        macaroon_path=base_dir / MACAROON_SUBPATH,
        tls_cert_path=base_dir / "tls.cert",
    )


@pytest.fixture(scope="session")
def tap_nodes(alice_tap, bob_tap, user_tap):
    # TODO: enable carol
    return [alice_tap, bob_tap, user_tap]


@pytest.fixture()
def user_evm_account(web3):
    account = Account.create()
    # Set initial balance for all created accounts
    initial_balance = Web3.to_wei(1, "ether")
    web3.provider.make_request(
        cast(RPCEndpoint, "hardhat_setBalance"),
        [account.address, to_hex(initial_balance)],
    )
    return account


@pytest.fixture()
def user_web3(user_evm_account) -> Web3:
    return create_web3(WEB3_RPC_URL, account=user_evm_account)


@pytest.fixture()
def user_bridge_contract(user_web3):
    return user_web3.eth.contract(
        address=BRIDGE_CONTRACT_ADDRESS,
        abi=load_abi("Bridge", abi_dir=ABI_DIR),
    )


@pytest.fixture(scope="session")
def alice_evm_account(web3):
    account = Account.from_key(ALICE_EVM_PRIVATE_KEY)
    # Set initial balance for all created accounts
    initial_balance = Web3.to_wei(1, "ether")
    web3.provider.make_request(
        cast(RPCEndpoint, "hardhat_setBalance"),
        [account.address, to_hex(initial_balance)],
    )
    return account


@pytest.fixture(scope="session")
def alice_web3(alice_evm_account) -> Web3:
    return create_web3(WEB3_RPC_URL, account=alice_evm_account)


@pytest.fixture(scope="session")
def owner_bridge_contract(alice_web3):
    return alice_web3.eth.contract(
        address=BRIDGE_CONTRACT_ADDRESS,
        abi=load_abi("Bridge", abi_dir=ABI_DIR),
    )


@pytest.fixture(scope="session")
def bridge_api():
    return BridgeAPIClient(base_url=NODE1_API_BASE_URL)
