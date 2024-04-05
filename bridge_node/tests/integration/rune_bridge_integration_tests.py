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
        abi=load_rune_bridge_abi("RuneToken"),
    )


@pytest.fixture()
def bitcoind():
    # Overrides default bitcoind fixture
    service = services.BitcoindService()
    assert service.is_started()
    return service


@pytest.fixture()
def ord(bitcoind):
    # Overrides default ord fixture
    service = services.OrdService(
        bitcoind=bitcoind,
    )
    assert service.is_started()
    return service


@pytest.fixture()
def alice_ord_wallet(ord, bitcoind):
    wallet = services.OrdWallet(
        ord=ord,
        name="alice-ord-test",
    )
    if not bitcoind.load_wallet("alice-ord-test"):
        logger.info("Creating alice-ord-test wallet")
        wallet.create()

    bitcoind.fund_wallets(wallet)

    balances = wallet.cli("balance")
    if RUNE_NAME not in balances["runes"]:
        wallet.etch_rune(
            rune=RUNE_NAME,
            supply_decimal=100000000,
            divisibility=18,
            symbol="R",
        )
        bitcoind.mine()

    return wallet


@pytest.fixture()
def user_ord_wallet(ord, bitcoind, bitcoin_rpc, alice_ord_wallet):
    wallet = services.OrdWallet(
        ord=ord,
        name="user-ord-test",
    )
    address = None
    if not bitcoind.load_wallet("user-ord-test"):
        logger.info("Creating user-ord-test wallet")
        wallet.create()

    bitcoind.fund_wallets(wallet)

    if wallet.get_rune_balance_decimal(RUNE_NAME) < 1000:
        if address is None:
            address = wallet.get_receiving_address()
            logger.info("USER ORD ADDRESS: %s", address)
        alice_ord_wallet.cli(
            "send",
            "--fee-rate",
            "1",
            address,
            f"1000:{RUNE_NAME}",
        )
        bitcoind.mine()

    return wallet


def test_integration_rune_bridge(
    user_evm_account,
    user_ord_wallet,
    user_evm_token,
    bridge_api,
    bitcoin_rpc,
    user_rune_bridge_contract,
    bitcoind,
):
    assert user_ord_wallet.get_rune_balance_decimal(RUNE_NAME) == 1000
    assert user_evm_token.functions.balanceOf(user_evm_account.address).call() == 0  # sanity check
    initial_total_supply = user_evm_token.functions.totalSupply().call()

    # Test runes to evm
    deposit_address = bridge_api.generate_rune_deposit_address(
        evm_address=user_evm_account.address,
    )
    logger.info("DEPOSIT ADDRESS: %s", deposit_address)
    user_ord_wallet.send_runes(
        receiver=deposit_address,
        amount_decimal=1000,
        rune=RUNE_NAME,
    )
    bitcoind.mine()

    user_evm_token_balance = wait_for_condition(
        callback=lambda: user_evm_token.functions.balanceOf(user_evm_account.address).call(),
        condition=lambda balance: balance > 0,
        description="user_evm_token_balance > 0",
    )

    assert from_wei(user_evm_token_balance) == 1000
    assert from_wei(user_evm_token.functions.totalSupply().call() - initial_total_supply) == 1000

    user_btc_address = user_ord_wallet.get_new_address()
    user_rune_bridge_contract.functions.transferToBtc(
        user_evm_token.address,
        to_wei(1000),
        user_btc_address,
    ).transact(
        {
            "gas": 10_000_000,
        }
    )

    def callback():
        bitcoind.mine()
        return user_ord_wallet.get_rune_balance_decimal(RUNE_NAME)

    user_rune_balance = wait_for_condition(
        callback=callback,
        condition=lambda balance: balance > 0,
        description="user_rune_balance > 0",
    )
    assert user_rune_balance == 1000
