from typing import Callable

import pytest
import logging

from web3 import Web3

from bridge.common.evm.utils import from_wei

logger = logging.getLogger(__name__)


@pytest.fixture(name="get_deposit_address")
def get_deposit_address_fixture(
    dbsession,
    rune_bridge_service,
) -> Callable[[str], str]:
    def get_deposit_address(evm_address: str):
        with dbsession.begin():
            return rune_bridge_service.generate_deposit_address(
                evm_address=evm_address,
                dbsession=dbsession,
            )

    return get_deposit_address


def test_sanity_checks(
    ord,
    user_evm_wallet,
    user_ord_wallet,
    root_ord_wallet,
    rune_name,
    rune_side_token_contract,
):
    assert user_ord_wallet.get_rune_balance_decimal(rune_name) == 0
    root_ord_wallet.send_runes(
        rune=rune_name,
        amount_decimal=1000,
        receiver=user_ord_wallet.get_receiving_address(),
    )
    ord.mine_and_sync()
    assert user_ord_wallet.get_rune_balance_decimal(rune_name) == 1000
    assert (
        rune_side_token_contract.functions.balanceOf(user_evm_wallet.address).call() == 0
    )  # sanity check
    initial_total_supply = rune_side_token_contract.functions.totalSupply().call()
    assert initial_total_supply == 0


def test_round_trip_happy_case(
    dbsession,
    hardhat,
    ord,
    user_evm_wallet,
    user_ord_wallet,
    root_ord_wallet,
    rune_name,
    rune_bridge_contract,
    rune_side_token_contract,
    rune_bridge,
    rune_bridge_service,
    get_deposit_address,
):
    root_ord_wallet.send_runes(
        rune=rune_name,
        amount_decimal=1000,
        receiver=user_ord_wallet.get_receiving_address(),
    )
    ord.mine_and_sync()

    # Test runes to evm
    deposit_address = get_deposit_address(user_evm_wallet.address)

    user_ord_wallet.send_runes(
        receiver=deposit_address,
        amount_decimal=1000,
        rune=rune_name,
    )
    ord.mine_and_sync()

    rune_bridge.run_iteration()

    hardhat.mine()

    user_evm_token_balance = rune_side_token_contract.functions.balanceOf(
        user_evm_wallet.address
    ).call()

    assert from_wei(user_evm_token_balance) == 1000
    assert from_wei(rune_side_token_contract.functions.totalSupply().call()) == 1000

    user_btc_address = user_ord_wallet.get_new_address()

    tx_hash = rune_bridge_contract.functions.transferToBtc(
        rune_side_token_contract.address,
        Web3.to_wei(1000, "ether"),
        user_btc_address,
    ).transact(
        {
            "gas": 10_000_000,
            "from": user_evm_wallet.address,
        }
    )

    hardhat.mine()

    receipt = hardhat.web3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt.status

    rune_bridge.run_iteration()

    ord.mine_and_sync()

    user_rune_balance = user_ord_wallet.get_rune_balance_decimal(rune_name)
    assert user_rune_balance == 1000
