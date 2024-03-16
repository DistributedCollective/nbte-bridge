import logging
import time

from sqlalchemy.orm import sessionmaker, Session

from bridge.bridges.runes.bridge import RuneBridge
from bridge.bridges.runes.faux_service import FauxRuneService
from bridge.common.evm.account import Account
from bridge.common.p2p.network import Network
from bridge.common.services.key_value_store import KeyValueStore

import pytest
from tests import services
from web3 import Web3
from web3.contract import Contract

from bridge.common.btc.rpc import BitcoinRPC
from bridge.common.evm.utils import load_abi
from bridge.bridges.runes.evm import load_rune_bridge_abi
from anemic.ioc import FactoryRegistrySet, Container
from bridge.common.services.transactions import register_transaction_manager

logger = logging.getLogger(__name__)


RUNE_BRIDGE_ADDRESS = "0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9"
RUNE_NAME = "MYRUNEISGOODER"
BTC_SLEEP_TIME = 2


@pytest.fixture(scope="module")
def evm_token(
    hardhat,
    alice_web3,
):
    deploy_response = hardhat.run_json_command("deploy-testtoken")
    address = deploy_response["address"]
    return alice_web3.eth.contract(
        address,
        abi=load_abi("TestToken"),
    )


@pytest.fixture(scope="module")
def user_rune_bridge_contract(
    user_web3,
) -> Contract:
    for _ in range(20):
        code = user_web3.eth.get_code(RUNE_BRIDGE_ADDRESS)
        if code and code != "0x":
            break
        logger.info("Rune bridge not yet deployed")
        time.sleep(2)
    else:
        raise TimeoutError("Rune bridge not deployed after waiting")

    return user_web3.eth.contract(
        address=RUNE_BRIDGE_ADDRESS,
        abi=load_rune_bridge_abi("RuneBridge"),
    )


@pytest.fixture(scope="module")
def user_evm_token(
    user_web3,
    user_rune_bridge_contract,
):
    return user_web3.eth.contract(
        address=user_rune_bridge_contract.functions.getTokenByRune(RUNE_NAME).call(),
        abi=load_rune_bridge_abi("RuneSideToken"),
    )


@pytest.fixture(scope="module")
def alice_ord_wallet(alice_ord, bitcoind):
    logger.info("Creating alice-ord-test wallet")
    wallet = services.OrdWallet(
        ord=alice_ord,
        name="alice-ord-test",
    )
    wallet.create()

    logger.info("Funding alice-ord-test wallet")
    address = wallet.cli("receive")["address"]
    logger.info("alice-ord-test address: %s", address)
    bitcoind.rpc.mine_blocks(101, address, sleep=BTC_SLEEP_TIME)

    wallet.cli(
        "etch",
        "--divisibility",
        "18",
        "--fee-rate",
        "1",
        "--rune",
        RUNE_NAME,
        "--supply",
        "100000000",
        "--symbol",
        "R",
    )
    bitcoind.rpc.mine_blocks(1, sleep=BTC_SLEEP_TIME)

    return wallet


@pytest.fixture(autouse=True, scope="module")
def bridge_wallet(bitcoind):
    logger.info("Creating and funding bridge wallet")
    wallet_name = "alice-ord"
    bitcoind.cli("createwallet", wallet_name)
    bridge_bitcoin_rpc = BitcoinRPC(url=bitcoind.get_wallet_rpc_url(wallet_name))
    address = bridge_bitcoin_rpc.call("getnewaddress")
    bitcoind.rpc.mine_blocks(101, address, sleep=BTC_SLEEP_TIME)


@pytest.fixture(scope="module")
def user_ord_wallet(user_ord, bitcoind, alice_ord_wallet):
    logger.info("Creating user-ord-test wallet")
    wallet = services.OrdWallet(
        ord=user_ord,
        name="user-ord-test",
    )
    wallet.create()

    logger.info("Funding user-ord-test wallet")
    address = wallet.cli("receive")["address"]
    bitcoind.rpc.mine_blocks(101, address, sleep=BTC_SLEEP_TIME)

    address = wallet.cli("receive")["address"]
    logger.info("user-ord-test address: %s", address)
    alice_ord_wallet.cli(
        "send",
        "--fee-rate",
        "1",
        address,
        f"1000 {RUNE_NAME}",
    )
    bitcoind.rpc.mine_blocks(1, sleep=BTC_SLEEP_TIME)

    return wallet


@pytest.fixture(scope="module")
def global_container(mock_network, alice_evm_account, alice_web3, dbengine):
    registries = FactoryRegistrySet()
    global_registry = registries.create_registry("global")
    transaction_registry = registries.create_registry("transaction")

    global_registry.register_singleton(
        interface=Network,
        singleton=mock_network[0],
    )

    global_registry.register_singleton(
        interface=Account,
        singleton=alice_evm_account,
    )

    global_registry.register_singleton(
        interface=Web3,
        singleton=alice_web3,
    )

    global_registry.register(
        interface=FauxRuneService,
        factory=FauxRuneService,
    )

    global_registry.register(
        interface=RuneBridge,
        factory=RuneBridge,
    )

    register_transaction_manager(
        global_registry=global_registry,
        transaction_registry=transaction_registry,
    )

    transaction_registry.register(
        interface=KeyValueStore,
        factory=KeyValueStore,
    )

    session_factory = sessionmaker(bind=dbengine)

    transaction_registry.register(
        interface=Session,
        factory=lambda _: session_factory(),
    )

    return Container(global_registry)


@pytest.fixture(scope="module")
def rune_bridge(global_container):
    return global_container.get(interface=RuneBridge)


@pytest.fixture(scope="module")
def rune_bridge_service(global_container):
    return global_container.get(interface=FauxRuneService)


def test_rune_bridge(
    user_evm_account,
    user_ord_wallet,
    user_evm_token,
    bitcoind,
    user_rune_bridge_contract,
    rune_bridge,
    rune_bridge_service,
    hardhat,
):
    assert user_ord_wallet.get_rune_balance(RUNE_NAME, divisibility=18) == 1000
    assert user_evm_token.functions.balanceOf(user_evm_account.address).call() == 0  # sanity check
    initial_total_supply = user_evm_token.functions.totalSupply().call()

    # Test runes to evm
    deposit_address = rune_bridge_service.generate_deposit_address(
        evm_address=user_evm_account.address,
    )
    logger.info("DEPOSIT ADDRESS: %s", deposit_address)
    user_ord_wallet.send_runes(
        receiver=deposit_address,
        amount=1000,
        rune=RUNE_NAME,
    )
    bitcoind.rpc.mine_blocks(2, sleep=BTC_SLEEP_TIME)

    hardhat.mine()

    rune_bridge.run_iteration()

    hardhat.mine()

    user_evm_token_balance = user_evm_token.functions.balanceOf(user_evm_account.address).call()

    assert Web3.from_wei(user_evm_token_balance, "ether") == 1000
    assert (
        Web3.from_wei(user_evm_token.functions.totalSupply().call() - initial_total_supply, "ether")
        == 1000
    )

    user_btc_address = user_ord_wallet.generate_address()

    print("TRANSFERRING TOKENS")
    tx_hash = user_rune_bridge_contract.functions.transferToBtc(
        user_evm_token.address,
        Web3.to_wei(1000, "ether"),
        user_btc_address,
    ).transact(
        {
            "gas": 10_000_000,
        }
    )

    hardhat.mine()
    receipt = hardhat.web3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt.status

    rune_bridge.run_iteration()
    bitcoind.rpc.mine_blocks(2, sleep=BTC_SLEEP_TIME)

    user_rune_balance = user_ord_wallet.get_rune_balance(RUNE_NAME, divisibility=18)
    assert user_rune_balance == 1000
