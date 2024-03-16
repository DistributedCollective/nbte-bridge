import os
import pathlib

from eth_account import Account
from eth_utils import to_hex
from sqlalchemy import create_engine
from web3 import Web3

from bridge.common.evm.utils import create_web3
from bridge.common.models.meta import Base

import pytest

from . import services
from .mock_network import MockNetwork

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
THIS_DIR = pathlib.Path(__file__).parent
INTEGRATION_TEST_DIR = THIS_DIR / "integration"

ALICE_EVM_PRIVATE_KEY = "0x9a9a640da1fc0181e43a9ea00b81878f26e1678e3e246b25bd2835783f2be181"

DEV_DB_NAME = "nbte_tmp_test"


def pytest_collection_modifyitems(config, items):
    for item in items:
        item_path = pathlib.Path(item.fspath)
        # Mark tests in the integration/ dir as integration tests
        if item_path.is_relative_to(INTEGRATION_TEST_DIR):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def postgres(request):
    return services.PostgresService(request)


@pytest.fixture(scope="module")
def hardhat(request):
    return services.HardhatService(request)


@pytest.fixture(scope="module")
def bitcoind(request):
    return services.BitcoindService(request)


@pytest.fixture(scope="module")
def alice_evm_account(web3):
    account = Account.from_key(ALICE_EVM_PRIVATE_KEY)
    # Set initial balance for all created accounts
    initial_balance = Web3.to_wei(1, "ether")
    web3.provider.make_request(
        "hardhat_setBalance",
        [account.address, to_hex(initial_balance)],
    )
    return account


@pytest.fixture(scope="module")
def user_evm_account(web3):
    account = Account.create()
    # Set initial balance for all created accounts
    initial_balance = Web3.to_wei(1, "ether")
    web3.provider.make_request(
        "hardhat_setBalance",
        [account.address, to_hex(initial_balance)],
    )
    return account


@pytest.fixture(scope="module")
def web3(hardhat) -> Web3:
    return hardhat.web3


@pytest.fixture(scope="module")
def alice_web3(hardhat, alice_evm_account) -> Web3:
    return create_web3(hardhat.rpc_url, account=alice_evm_account)


@pytest.fixture(scope="module")
def user_web3(hardhat, user_evm_account) -> Web3:
    return create_web3(hardhat.rpc_url, account=user_evm_account)


@pytest.fixture(scope="module")
def user_ord(request):
    return services.OrdService(service="user-ord", request=request)


@pytest.fixture(scope="module")
def alice_ord(request):
    return services.OrdService(service="alice-ord", request=request)


@pytest.fixture(scope="module")
def mock_network():
    leader = MockNetwork(node_id="alice", leader=True)
    follower1 = MockNetwork(node_id="bob")
    follower2 = MockNetwork(node_id="carol")

    leader.add_peers([follower1, follower2])
    follower1.add_peers([leader, follower2])
    follower2.add_peers([leader, follower1])

    return leader, follower1, follower2


@pytest.fixture(scope="module")
def dbengine(postgres):
    postgres.cli(f"DROP DATABASE IF EXISTS {DEV_DB_NAME};")
    postgres.cli(f"CREATE DATABASE {DEV_DB_NAME};")

    engine = create_engine(postgres.dsn_outside_docker, echo=False)
    Base.metadata.create_all(engine)
    return engine


# TODO: we can have something like this but not necessarily yet
# @pytest.fixture(scope="module")
# def dbsession(engine):
#     session = Session(bind=engine)
#     yield session
#     session.rollback()
