import logging

import pytest
from web3.contract import Contract

from bridge.common.evm.utils import load_abi
from bridge.bridges.runes.evm import load_rune_bridge_abi
from .. import services
from .utils import wait_for_condition, from_wei, to_wei

logger = logging.getLogger(__name__)


RUNE_BRIDGE_ADDRESS = "0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9"
RUNE_NAME = "MYRUNEISGOODER"
BTC_SLEEP_TIME = 5


@pytest.fixture()
def evm_token(
    harness,
    alice_web3,
):
    deploy_response = harness.run_hardhat_json_command("deploy-testtoken")
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
def user_ord():
    service = services.OrdService(
        service="user-ord",
    )
    assert service.is_started()
    return service


@pytest.fixture()
def alice_ord():
    service = services.OrdService(
        service="alice-ord",
    )
    assert service.is_started()
    return service


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


def test_rune_bridge(
    user_evm_account,
    user_ord_wallet,
    user_evm_token,
    bridge_api,
    bitcoin_rpc,
    user_rune_bridge_contract,
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

    user_evm_token_balance = wait_for_condition(
        callback=lambda: user_evm_token.functions.balanceOf(user_evm_account.address).call(),
        condition=lambda balance: balance > 0,
        description="user_evm_token_balance > 0",
    )

    assert from_wei(user_evm_token_balance) == 1000
    assert from_wei(user_evm_token.functions.totalSupply().call() - initial_total_supply) == 1000

    # TODO test evm to runes
    return
    user_btc_address = user_ord_wallet.generate_address()
    user_rune_bridge_contract.functions.transferToBtc(
        user_evm_token.address,
        to_wei(1000),
        user_btc_address,
    )

    def callback():
        bitcoin_rpc.mine_blocks(1, sleep=BTC_SLEEP_TIME)
        return user_ord_wallet.get_rune_balance(RUNE_NAME, divisibility=18)

    user_rune_balance = wait_for_condition(
        callback=callback,
        condition=lambda balance: balance > 0,
        description="user_rune_balance > 0",
    )
    assert user_rune_balance == 1000
