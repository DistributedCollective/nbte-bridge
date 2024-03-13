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
BTC_SLEEP_TIME = 1


@pytest.fixture()
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


@pytest.fixture()
def user_rune_bridge_contract(
    user_web3,
) -> Contract:
    return user_web3.eth.contract(
        address=RUNE_BRIDGE_ADDRESS,
        abi=load_rune_bridge_abi("RuneBridge"),
    )


@pytest.fixture()
def user_evm_token(
    user_web3,
    user_rune_bridge_contract,
):
    return user_web3.eth.contract(
        address=user_rune_bridge_contract.functions.getTokenByRune(RUNE_NAME).call(),
        abi=load_rune_bridge_abi("RuneSideToken"),
    )


@pytest.fixture()
def alice_ord_wallet(alice_ord, bitcoin_rpc):
    wallet = services.OrdWallet(
        ord=alice_ord,
        name="alice-ord-test",
    )
    wallets = bitcoin_rpc.call("listwallets")
    if wallet.name not in wallets:
        logger.info("Creating alice-ord-test wallet")
        wallet.create()

    balances = wallet.cli("balance")
    if balances["cardinal"] < 100:
        logger.info("Funding alice-ord-test wallet")
        address = wallet.cli("receive")["address"]
        logger.info("ALICE ORD ADDRESS: %s", address)
        bitcoin_rpc.mine_blocks(101, address, sleep=BTC_SLEEP_TIME)

    if RUNE_NAME not in balances["runes"]:
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
        bitcoin_rpc.mine_blocks(1, sleep=BTC_SLEEP_TIME)

    return wallet


@pytest.fixture(autouse=True)
def bridge_wallet(bitcoin_rpc):
    wallet_name = "alice-ord"
    wallets = bitcoin_rpc.call("listwallets")
    if wallet_name not in wallets:
        logger.info("Creating alice-ord wallet")
        bitcoin_rpc.call("createwallet", wallet_name)
        time.sleep(BTC_SLEEP_TIME)

    bitcoin_rpc = BitcoinRPC(url="http://polaruser:polarpass@localhost:18443/wallet/alice-ord")
    address = bitcoin_rpc.call("getnewaddress")
    bitcoin_rpc.mine_blocks(101, address, sleep=BTC_SLEEP_TIME)


@pytest.fixture()
def user_ord_wallet(user_ord, bitcoin_rpc, alice_ord_wallet):
    wallet = services.OrdWallet(
        ord=user_ord,
        name="user-ord-test",
    )
    wallets = bitcoin_rpc.call("listwallets")
    address = None
    if wallet.name not in wallets:
        logger.info("Creating user-ord-test wallet")
        wallet.create()

    balances = wallet.cli("balance")
    if balances["cardinal"] < 1000:
        logger.info("Funding user-ord-test wallet")
        address = wallet.cli("receive")["address"]
        logger.info("USER ORD ADDRESS: %s", address)
        bitcoin_rpc.mine_blocks(101, address, sleep=BTC_SLEEP_TIME)

    if balances["runes"].get(RUNE_NAME, 0) < 1000 * 10**18:
        if address is None:
            address = wallet.cli("receive")["address"]
            logger.info("USER ORD ADDRESS: %s", address)
        alice_ord_wallet.cli(
            "send",
            "--fee-rate",
            "1",
            address,
            f"1000 {RUNE_NAME}",
        )
        bitcoin_rpc.mine_blocks(1, sleep=BTC_SLEEP_TIME)

    return wallet


@pytest.fixture()
def rune_bridge(mock_network, alice_evm_account, alice_web3, dbengine):
    registries = FactoryRegistrySet()
    global_registry = registries.create_registry("global")
    transaction_registry = registries.create_registry("transaction")

    global_registry.register_singleton(
        interface=Network,
        instance=mock_network[0],
    )

    global_registry.register_singleton(
        interface=Account,
        instance=alice_evm_account,
    )

    global_registry.register_singleton(
        interface=Web3,
        instance=alice_web3,
    )

    global_registry.register(
        interface=FauxRuneService,
        factory=FauxRuneService,
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
        factory=session_factory,
    )

    global_container = Container(global_registry)

    rune_bridge = RuneBridge(global_container)

    return rune_bridge


def test_rune_bridge(
    user_evm_account,
    user_ord_wallet,
    user_evm_token,
    bridge_api,
    bitcoin_rpc,
    user_rune_bridge_contract,
    rune_bridge,
):
    assert user_ord_wallet.get_rune_balance(RUNE_NAME, divisibility=18) == 1000
    assert user_evm_token.functions.balanceOf(user_evm_account.address).call() == 0  # sanity check
    initial_total_supply = user_evm_token.functions.totalSupply().call()

    # Test runes to evm
    deposit_address = bridge_api.generate_rune_deposit_address(
        evm_address=user_evm_account.address,
    )
    logger.info("DEPOSIT ADDRESS: %s", deposit_address)
    user_ord_wallet.send_runes(
        receiver=deposit_address,
        amount=1000,
        rune=RUNE_NAME,
    )
    bitcoin_rpc.mine_blocks(1, sleep=BTC_SLEEP_TIME)

    rune_bridge.run_iteration()

    time.sleep(20)

    user_evm_token_balance = user_evm_token.functions.balanceOf(user_evm_account.address).call()

    assert Web3.from_wei(user_evm_token_balance) == 1000
    assert (
        Web3.from_wei(user_evm_token.functions.totalSupply().call() - initial_total_supply) == 1000
    )

    user_btc_address = user_ord_wallet.generate_address()
    user_rune_bridge_contract.functions.transferToBtc(
        user_evm_token.address,
        Web3.to_wei(1000),
        user_btc_address,
    ).transact(
        {
            "gas": 10_000_000,
        }
    )

    time.sleep(20)

    bitcoin_rpc.mine_blocks(1)

    user_rune_balance = user_ord_wallet.get_rune_balance(RUNE_NAME, divisibility=18)
    assert user_rune_balance == 1000
