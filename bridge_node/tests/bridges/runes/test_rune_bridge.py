import logging


logger = logging.getLogger(__name__)


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
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    rune_name,
):
    bridge_util.fund_wallet_with_runes(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        rune=rune_name,
    )

    # Test runes to evm

    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)
    bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        deposit_address=deposit_address,
        rune=rune_name,
    )

    initial_balances = bridge_util.snapshot_balances(
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        rune=rune_name,
    )
    initial_balances.assert_values(
        bridge_rune_balance_decimal=1000,
        # Other values are asserted to equal 0
    )

    bridge_util.run_bridge_iteration()

    bridge_util.snapshot_balances_again(initial_balances).assert_values(
        user_token_balance_decimal=1000,
        token_total_supply_decimal=1000,
        bridge_rune_balance_decimal=1000,
    )

    # Test EVM to Runes

    rune_token = bridge_util.get_rune_token(rune_name)
    user_btc_address = user_ord_wallet.get_new_address()
    bridge_util.transfer_rune_tokens_to_bitcoin(
        sender=user_evm_wallet,
        rune_token_address=rune_token.address,
        amount_decimal=1000,
        receiver_address=user_btc_address,
    )

    bridge_util.snapshot_balances_again(initial_balances).assert_values(
        bridge_rune_balance_decimal=1000,
    )

    bridge_util.run_bridge_iteration()

    bridge_util.snapshot_balances_again(initial_balances).assert_values(
        user_rune_balance_decimal=1000,
    )
