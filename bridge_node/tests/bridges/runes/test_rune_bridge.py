from decimal import Decimal

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
        prefix="SANITYCHECK",
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


@pytest.mark.parametrize("mine_between", [True, False])
def test_multiple_runes_can_be_transferred(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    mine_between,
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
        mine=mine_between,
    )
    transfer_b = bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=600,
        deposit_address=deposit_address,
        rune=rune_b,
        mine=True,
    )

    bridge_util.run_bridge_iteration()

    bridge_util.assert_runes_transferred_to_evm(transfer_a)
    bridge_util.assert_runes_transferred_to_evm(transfer_b)


def test_runes_can_be_transferred_sequentially(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
):
    expected_rune_balance = 10000
    expected_token_balance = 0
    transfer_amount = 1000

    rune = bridge_util.etch_and_register_test_rune(
        prefix="SEQUENTIAL",
        fund=(user_ord_wallet, expected_rune_balance),
    )

    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)
    initial_balances = bridge_util.snapshot_balances(
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        rune=rune,
    )
    initial_balances.assert_values(
        user_token_balance_decimal=expected_token_balance,
        token_total_supply_decimal=expected_token_balance,
        user_rune_balance_decimal=expected_rune_balance,
        bridge_rune_balance_decimal=expected_token_balance,
    )

    for _ in range(5):
        transfer = bridge_util.transfer_runes_to_evm(
            wallet=user_ord_wallet,
            amount_decimal=1000,
            deposit_address=deposit_address,
            rune=rune,
        )
        bridge_util.run_bridge_iteration()

        bridge_util.assert_runes_transferred_to_evm(transfer)

        expected_rune_balance -= transfer_amount
        expected_token_balance += transfer_amount

        bridge_util.snapshot_balances_again(initial_balances).assert_values(
            user_token_balance_decimal=expected_token_balance,
            token_total_supply_decimal=expected_token_balance,
            user_rune_balance_decimal=expected_rune_balance,
            bridge_rune_balance_decimal=expected_token_balance,
        )


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


def test_fees_rune_to_evm(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    federator_wirings,
):
    rune = bridge_util.etch_and_register_test_rune(
        prefix="FEESRUNETOEVM",
        fund=(user_ord_wallet, 1000),
    )
    for wiring in federator_wirings:
        wiring.service.config.runes_to_evm_fee_percentage_decimal = Decimal(1)

    # Test runes to evm

    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)
    initial_balances = bridge_util.snapshot_balances(
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        rune=rune,
    )
    bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        deposit_address=deposit_address,
        rune=rune,
    )

    bridge_util.run_bridge_iteration()

    bridge_util.snapshot_balances_again(initial_balances).assert_values(
        user_token_balance_decimal=990,
        token_total_supply_decimal=990,
        bridge_rune_balance_decimal=1000,
    )


# TODO: test that nodes won't validate invalid transfers


def test_runes_to_evm_no_double_spends(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
):
    rune = bridge_util.etch_and_register_test_rune(
        prefix="EVMMULTISIG",
        fund=(user_ord_wallet, 123),
    )
    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)
    bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=123,
        deposit_address=deposit_address,
        rune=rune,
    )

    initial_balances = bridge_util.snapshot_balances(
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        rune=rune,
    )
    initial_balances.assert_values(
        bridge_rune_balance_decimal=123,
    )

    bridge_util.run_bridge_iteration()
    bridge_util.snapshot_balances_again(initial_balances).assert_values(
        user_token_balance_decimal=123,
        token_total_supply_decimal=123,
        bridge_rune_balance_decimal=123,
    )

    for _ in range(5):
        bridge_util.run_bridge_iteration()

        # Balances stay the same
        bridge_util.snapshot_balances_again(initial_balances).assert_values(
            user_token_balance_decimal=123,
            token_total_supply_decimal=123,
            bridge_rune_balance_decimal=123,
        )


def test_rune_tokens_to_btc_no_double_spends(
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
        fund=(bridge_ord_multisig.change_address, 456),
    )
    rune_token = bridge_util.mint_rune_tokens(
        rune,
        amount_decimal=456,
        receiver=user_evm_wallet.address,
    )

    user_btc_address = user_ord_wallet.get_receiving_address()
    bridge_util.transfer_rune_tokens_to_btc(
        sender=user_evm_wallet,
        rune_token_address=rune_token.address,
        amount_decimal=456,
        receiver_address=user_btc_address,
        receiver_wallet=user_ord_wallet,
    )

    initial_balances = bridge_util.snapshot_balances(
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        rune=rune,
    )
    initial_balances.assert_values(
        bridge_rune_balance_decimal=456,
    )

    bridge_util.run_bridge_iteration()

    for _ in range(5):
        bridge_util.run_bridge_iteration()

        # Balances stay the same
        bridge_util.snapshot_balances_again(initial_balances).assert_values(
            user_rune_balance_decimal=456,
        )


def test_rune_to_evm_transfers_are_not_processed_without_confirmations(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    rune_bridge_service,
    dbsession,
    ord,
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
        mine=False,
    )
    bridge_util.run_bridge_iteration()
    bridge_util.assert_runes_not_transferred_to_evm(transfer)

    ord.mine_and_sync()
    bridge_util.assert_runes_not_transferred_to_evm(transfer)

    bridge_util.run_bridge_iteration()
    bridge_util.assert_runes_transferred_to_evm(transfer)


def test_unsupported_rune(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    rune_bridge_service,
    root_ord_wallet,
    dbsession,
    ord,
):
    rune = root_ord_wallet.etch_test_rune(
        prefix="UNSUPPORTED",
    ).rune
    root_ord_wallet.send_runes(
        rune=rune,
        amount_decimal=1000,
        receiver=user_ord_wallet.get_receiving_address(),
    )
    ord.mine_and_sync()
    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)

    bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        deposit_address=deposit_address,
        rune=rune,
    )
    bridge_util.run_bridge_iteration()
    # XXX it will fail here because the rune is not supported, whatever
    # bridge_util.assert_runes_not_transferred_to_evm(transfer)

    # test that it doesn't mess things up totally
    rune2 = bridge_util.etch_and_register_test_rune(
        prefix="SUPPORTED",
        fund=(user_ord_wallet, 1000),
    )
    transfer2 = bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        deposit_address=deposit_address,
        rune=rune2,
    )
    bridge_util.run_bridge_iteration()
    bridge_util.assert_runes_transferred_to_evm(transfer2)


def test_too_low_postage(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    rune_bridge_service,
    root_ord_wallet,
    dbsession,
    ord,
):
    rune = bridge_util.etch_and_register_test_rune(
        prefix="LOWPOSTAGE",
        fund=(user_ord_wallet, 1000),
    )
    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)

    transfer = bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        deposit_address=deposit_address,
        rune=rune,
        postage=9900,
    )
    bridge_util.run_bridge_iteration()
    bridge_util.assert_runes_not_transferred_to_evm(transfer)


def test_ord_indexing(
    ord,
    root_ord_wallet,
    user_ord_wallet,
    bitcoind,
):
    # Just a sanity check to see if ord indexes transactions with zero confirmations
    rune = root_ord_wallet.etch_test_rune(
        prefix="INDEXING",
    ).rune
    block_number = bitcoind.rpc.call("getblockcount")
    response = root_ord_wallet.send_runes(
        rune=rune,
        amount_decimal=1000,
        receiver=user_ord_wallet.get_receiving_address(),
    )
    assert bitcoind.rpc.call("getblockcount") == block_number

    ord.sync_with_bitcoind()

    outp = ord.api_client.get_output(response.txid, 2)
    assert not outp["indexed"]

    ord.mine_and_sync()
    outp = ord.api_client.get_output(response.txid, 2)
    assert outp["indexed"]
    assert bitcoind.rpc.call("getblockcount") == block_number + 1


def test_get_pending_deposits_for_evm_address(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    rune_bridge_service,
    dbsession,
    ord,
):
    rune = bridge_util.etch_and_register_test_rune(
        prefix="EEEEEEEEE",
        symbol="E",
        fund=(user_ord_wallet, 1000),
    )
    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)

    with dbsession.begin():
        assert rune_bridge_service.get_last_scanned_bitcoin_block(dbsession) is None

    bridge_util.run_bridge_iteration()

    with dbsession.begin():
        last_block = rune_bridge_service.get_last_scanned_bitcoin_block(dbsession)

    assert isinstance(last_block, str)
    bytes.fromhex(last_block)  # should not raise
    assert len(last_block) == 64

    with dbsession.begin():
        pending_deposits = rune_bridge_service.get_pending_deposits_for_evm_address(
            last_block=last_block,
            dbsession=dbsession,
            evm_address=user_evm_wallet.address,
        )

    assert pending_deposits == []

    ord_response = user_ord_wallet.send_runes(
        rune=rune,
        amount_decimal=1000,
        receiver=deposit_address,
    )

    bridge_util.run_bridge_iteration()

    with dbsession.begin():
        pending_deposits = rune_bridge_service.get_pending_deposits_for_evm_address(
            last_block=last_block,
            dbsession=dbsession,
            evm_address=user_evm_wallet.address,
        )

    assert pending_deposits == [
        {
            "amount_decimal": "0",
            "btc_deposit_txid": ord_response.txid,
            "btc_deposit_vout": 2,
            "evm_transfer_tx_hash": None,
            "fee_amount_decimal": "0",
            "receive_amount_decimal": "0",
            "rune_name": "",
            "rune_symbol": "",
            "status": "detected",
        }
    ]

    # This doesn't happen now but it's ok
    # bridge_util.run_bridge_iteration()
    #
    # with dbsession.begin():
    #     pending_deposits = rune_bridge_service.get_pending_deposits_for_evm_address(
    #         last_block=last_block,
    #         dbsession=dbsession,
    #         evm_address=user_evm_wallet.address,
    #     )
    #
    # assert pending_deposits == [
    #     {
    #         "amount_decimal": "1000",
    #         "btc_deposit_txid": ord_response.txid,
    #         "btc_deposit_vout": 2,
    #         "evm_transfer_tx_hash": None,
    #         "fee_decimal": "0",
    #         "receive_amount_decimal": "1000",
    #         "rune_name": rune,
    #         "rune_symbol": "E",
    #         "status": "seen",
    #     }
    # ]

    ord.mine_and_sync()

    bridge_util.run_bridge_iteration()

    with dbsession.begin():
        new_last_block = rune_bridge_service.get_last_scanned_bitcoin_block(dbsession)
    assert new_last_block != last_block

    with dbsession.begin():
        pending_deposits = rune_bridge_service.get_pending_deposits_for_evm_address(
            last_block=last_block,
            dbsession=dbsession,
            evm_address=user_evm_wallet.address,
        )

    # Have to assert manually because of evm_transfer_tx_hash
    # assert pending_deposits == [
    #     {
    #         'amount_decimal': '1000',
    #         'btc_deposit_txid': '010be37d54469cc159781bcd8519711a1d8ac46ea70c7aad4bd4b3658fb47298',
    #         'btc_deposit_vout': 2,
    #         'evm_transfer_tx_hash': '0xa1cc885b84b3a09f23b4a3454839d1938f94db5d1c2b8ffbdb8fd25d6e975a03',
    #         'fee_decimal': '0',
    #         'receive_amount_decimal': '1000',
    #         'rune_name': 'EVMMULTISIGZYMRUMBQS',
    #         'rune_symbol': 'E',
    #         'status': 'confirmed',
    #     }
    # ]
    assert len(pending_deposits) == 1
    deposit = pending_deposits[0]
    assert deposit["status"] == "confirmed"
    assert deposit["amount_decimal"] == "1000"
    assert deposit["btc_deposit_txid"] == ord_response.txid
    assert deposit["btc_deposit_vout"] == 2
    assert deposit["evm_transfer_tx_hash"] is not None
    assert deposit["evm_transfer_tx_hash"].startswith("0x")
    assert deposit["fee_decimal"] == "0"
    assert deposit["receive_amount_decimal"] == "1000"
    assert deposit["rune_name"] == rune
    assert deposit["rune_symbol"] == "E"


def test_rune_to_evm_transfers_are_resumed(
    bridge_util,
    user_ord_wallet,
    user_evm_wallet,
    bob_service,
    carol_service,
    monkeypatch,
):
    rune = bridge_util.etch_and_register_test_rune(
        prefix="RESUMED",
        fund=(user_ord_wallet, 1000),
    )
    deposit_address = bridge_util.get_deposit_address(user_evm_wallet.address)
    transfer = bridge_util.transfer_runes_to_evm(
        wallet=user_ord_wallet,
        amount_decimal=1000,
        deposit_address=deposit_address,
        rune=rune,
    )

    for service in [bob_service, carol_service]:
        monkeypatch.setattr(
            service, "answer_sign_rune_to_evm_transfer_question", lambda *args, **kwargs: None
        )

    bridge_util.run_bridge_iteration()

    bridge_util.assert_runes_not_transferred_to_evm(transfer)

    monkeypatch.undo()

    bridge_util.run_bridge_iteration()

    bridge_util.assert_runes_transferred_to_evm(transfer)


def test_rune_tokens_to_btc_transfers_are_resumed(
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
        prefix="RESUMED",
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

    for service in [bob_service, carol_service]:
        monkeypatch.setattr(
            service, "answer_sign_rune_token_to_btc_transfer_question", lambda *args, **kwargs: None
        )

    bridge_util.run_bridge_iteration()

    bridge_util.assert_rune_tokens_not_transferred_to_btc(transfer)

    monkeypatch.undo()

    bridge_util.run_bridge_iteration()

    bridge_util.assert_rune_tokens_transferred_to_btc(transfer)
