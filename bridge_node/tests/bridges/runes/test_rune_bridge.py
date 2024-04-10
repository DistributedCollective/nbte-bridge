import pytest
import logging


logger = logging.getLogger(__name__)


def test_sanity_checks(
    ord,
    user_evm_wallet,
    user_ord_wallet,
    root_ord_wallet,
    bridge_util,
):
    rune_name = bridge_util.etch_and_register_test_rune(
        prefix="ROUNDTRIP",
    )
    rune_side_token_contract = bridge_util.get_rune_token(rune_name)
    assert user_ord_wallet.get_rune_balance_decimal(rune_name) == 0
    root_ord_wallet.send_runes(
        rune=rune_name,
        amount_decimal=1000,
        receiver=user_ord_wallet.get_receiving_address(),
    )
    ord.mine_and_sync()
    assert user_ord_wallet.get_rune_balance_decimal(rune_name) == 1000
    assert rune_side_token_contract.functions.balanceOf(user_evm_wallet.address).call() == 0
    initial_total_supply = rune_side_token_contract.functions.totalSupply().call()
    assert initial_total_supply == 0


def test_round_trip_happy_case(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
):
    rune = bridge_util.etch_and_register_test_rune(
        prefix="ROUNDTRIP",
        fund=(user_ord_wallet, 1000),
    )

    # Test runes to evm

    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)
    transfer = bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        deposit_address=deposit_address,
        rune=rune,
    )

    bridge_util.assert_runes_not_transferred_to_evm(transfer)  # not yet!

    initial_balances = bridge_util.snapshot_balances(
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        rune=rune,
    )
    initial_balances.assert_values(
        bridge_rune_balance_decimal=1000,
        # Other values are asserted to equal 0
    )

    bridge_util.run_bridge_iteration()

    bridge_util.assert_runes_transferred_to_evm(transfer)

    bridge_util.snapshot_balances_again(initial_balances).assert_values(
        user_token_balance_decimal=1000,
        token_total_supply_decimal=1000,
        bridge_rune_balance_decimal=1000,
    )

    # Test EVM to Runes

    rune_token = bridge_util.get_rune_token(rune)
    user_btc_address = user_ord_wallet.get_new_address()
    transfer = bridge_util.transfer_rune_tokens_to_btc(
        sender=user_evm_wallet,
        rune_token_address=rune_token.address,
        amount_decimal=1000,
        receiver_address=user_btc_address,
        receiver_wallet=user_ord_wallet,
    )

    bridge_util.assert_rune_tokens_not_transferred_to_btc(transfer)  # not yet!

    bridge_util.snapshot_balances_again(initial_balances).assert_values(
        bridge_rune_balance_decimal=1000,
    )

    bridge_util.run_bridge_iteration()

    bridge_util.assert_rune_tokens_transferred_to_btc(transfer)  # not yet!

    bridge_util.snapshot_balances_again(initial_balances).assert_values(
        user_rune_balance_decimal=1000,
    )


def test_multiple_runes_can_be_transferred(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
):
    rune_a = bridge_util.etch_and_register_test_rune(
        prefix="MULTIAAA",
        fund=(user_ord_wallet, 1000),
    )
    rune_b = bridge_util.etch_and_register_test_rune(
        prefix="MULTIBBB",
        fund=(user_ord_wallet, 1000),
    )

    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)
    transfer_a = bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=400,
        deposit_address=deposit_address,
        rune=rune_a,
    )
    transfer_b = bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=600,
        deposit_address=deposit_address,
        rune=rune_b,
    )

    bridge_util.run_bridge_iteration()

    bridge_util.assert_runes_transferred_to_evm(transfer_a)
    bridge_util.assert_runes_transferred_to_evm(transfer_b)


@pytest.mark.parametrize(
    "enable_bob,enable_carol,expected_transfer_happened",
    [
        (True, True, True),
        (True, False, True),
        (False, True, True),
        (False, False, False),
    ],
)
def test_runes_to_evm_transfers_require_signatures_from_the_majority_of_nodes(
    enable_bob,
    enable_carol,
    expected_transfer_happened,
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    bob_service,
    carol_service,
    monkeypatch,
):
    rune = bridge_util.etch_and_register_test_rune(
        prefix="EVMMULTISIG",
        fund=(user_ord_wallet, 1000),
    )
    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)
    transfer = bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        deposit_address=deposit_address,
        rune=rune,
    )

    for enable, service in [(enable_bob, bob_service), (enable_carol, carol_service)]:
        if not enable:
            monkeypatch.setattr(
                service, "answer_sign_rune_to_evm_transfer_question", lambda *args, **kwargs: None
            )

    bridge_util.run_bridge_iteration()

    if expected_transfer_happened:
        bridge_util.assert_runes_transferred_to_evm(transfer)
    else:
        bridge_util.assert_runes_not_transferred_to_evm(transfer)


@pytest.mark.parametrize(
    "enable_bob,enable_carol,expected_transfer_happened",
    [
        (True, True, True),
        (True, False, True),
        (False, True, True),
        (False, False, False),
    ],
)
def test_rune_tokens_to_btc_transfers_require_signatures_from_the_majority_of_nodes(
    enable_bob,
    enable_carol,
    expected_transfer_happened,
    bridge_util,
    bridge_ord_multisig,
    user_ord_wallet,
    user_evm_wallet,
    bob_service,
    carol_service,
    monkeypatch,
    hardhat,
):
    rune = bridge_util.etch_and_register_test_rune(
        prefix="ORDMULTISIG",
        fund=(bridge_ord_multisig.change_address, 1000),
    )
    rune_token = bridge_util.mint_rune_tokens(
        rune,
        amount_decimal=1000,
        receiver=user_evm_wallet.address,
    )

    user_btc_address = user_ord_wallet.get_receiving_address()
    transfer = bridge_util.transfer_rune_tokens_to_btc(
        sender=user_evm_wallet,
        rune_token_address=rune_token.address,
        amount_decimal=1000,
        receiver_address=user_btc_address,
        receiver_wallet=user_ord_wallet,
    )

    for enable, service in [(enable_bob, bob_service), (enable_carol, carol_service)]:
        if not enable:
            monkeypatch.setattr(
                service,
                "answer_sign_rune_token_to_btc_transfer_question",
                lambda *args, **kwargs: None,
            )

    bridge_util.run_bridge_iteration()

    if expected_transfer_happened:
        bridge_util.assert_rune_tokens_transferred_to_btc(transfer)
    else:
        bridge_util.assert_rune_tokens_not_transferred_to_btc(transfer)


# TODO: test that nodes won't validate invalid transfers
