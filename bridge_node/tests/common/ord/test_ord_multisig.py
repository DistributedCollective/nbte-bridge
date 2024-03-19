from decimal import Decimal

import pytest
from bridge.common.ord.multisig import OrdMultisig
from bridge.common.ord.transfers import RuneTransfer
from bridge.common.utils import to_base_units, to_decimal
from tests.services import BitcoindService, OrdService, OrdWallet

MULTISIG_XPRVS = [
    "tprv8ZgxMBicQKsPdLiVtqrvinq5JyvByQZs4xWMgzZ3YWK7ndu27yQ3qoWivh8cgdtB3bKuYKWRKhaEvtykaFCsDCB7akNdcArjgrCnFhuDjmV",
    "tprv8ZgxMBicQKsPdMXsXv4Ddkgimo1m89QjXBNUrCgAaDRX5tEDMVA8HotnZmHcMvUVtgh1yXbN74StoJqv76jvRxJmkr2wvkPwTbZb1zeXv3Y",
    "tprv8ZgxMBicQKsPcwXzdBoYKEXmLiBsPzNRfoLadw8WsnmKSHU47fJR3UjAhni8kt5bx5jFG9JZ4oZuxnaX6beTNwc2C5coMHmAvnKpqHA8xVb",
]
MULTISIG_XPUBS = [
    "tpubD6NzVbkrYhZ4WokHnVXX8CVBt1S88jkmeG78yWbLxn7Wd89nkNDe2J8b6opP4K38mRwXf9d9VVN5uA58epPKjj584R1rnDDbk6oHUD1MoWD",
    "tpubD6NzVbkrYhZ4WpZfRZip3ALqLpXhHUbe6UyG8iiTzVDuvNUyysyiUJWejtbszZYrDaUM8UZpjLmHyvtV7r1QQNFmTqciAz1fYSYkw28Ux6y",
    "tpubD6NzVbkrYhZ4WQZnWqU8ieBsujhoZKZLF6wMvTApJ4ZiGmipk481DyM2su3y5BDeB9fFLwSmmmsGDGJum79he2fnuQMnpWhe3bGir7Mf4uS",
]
MULTISIG_KEY_DERIVATION_PATH = "m/0/0"


@pytest.fixture()
def multisig_factory(
    bitcoind: BitcoindService,
    ord: OrdService,
):
    def create_multisig(
        required: int,
        xpriv: str,
        xpubs: list[str],
        key_derivation_path: str = MULTISIG_KEY_DERIVATION_PATH,
        *,
        fund: bool = True,
    ):
        wallet = bitcoind.create_test_wallet(
            prefix=f"ord-multisig-{required}-of-{len(xpubs)}",
            watchonly=True,
        )
        multisig = OrdMultisig(
            master_xpriv=xpriv,
            master_xpubs=xpubs,
            num_required_signers=required,
            key_derivation_path=key_derivation_path,
            bitcoin_rpc=wallet.rpc,
            ord_client=ord.api_client,
        )
        wallet.rpc.call(
            "importdescriptors",
            [
                {
                    "desc": multisig.get_descriptor(),
                    "timestamp": "now",
                }
            ],
        )
        if fund:
            bitcoind.fund_addresses(multisig.change_address)
        return multisig

    return create_multisig


@pytest.fixture()
def multisig(multisig_factory):
    return multisig_factory(
        required=2,
        xpriv=MULTISIG_XPRVS[0],
        xpubs=MULTISIG_XPUBS,
        key_derivation_path=MULTISIG_KEY_DERIVATION_PATH,
    )


def test_verify_descriptor(
    multisig,
    bitcoind,
):
    derived_addresses = bitcoind.rpc.call("deriveaddresses", multisig.get_descriptor())
    if derived_addresses != [multisig.change_address]:
        raise ValueError(
            f"Multisig address derivation failed, "
            f"got {derived_addresses}, expected [{multisig.change_address}]"
        )


def test_get_rune_balance(
    ord: OrdService,
    bitcoind: BitcoindService,
    rune_factory,
    root_ord_wallet: OrdWallet,
    multisig,
):
    rune_a, rune_b = rune_factory("AAAA", "BBBB")
    assert multisig.get_rune_balance(rune_a) == 0
    assert multisig.get_rune_balance(rune_b) == 0

    root_ord_wallet.send_runes(
        rune=rune_a,
        amount=Decimal("123.4"),
        receiver=multisig.change_address,
    )
    ord.mine_and_sync(bitcoind)

    assert to_decimal(multisig.get_rune_balance(rune_a), 18) == Decimal("123.4")
    assert multisig.get_rune_balance(rune_b) == 0


def test_1_of_2_send_runes(
    ord: OrdService,
    bitcoind: BitcoindService,
    rune_factory,
    multisig_factory,
):
    multisig = multisig_factory(
        required=1,
        xpriv=MULTISIG_XPRVS[0],
        xpubs=MULTISIG_XPUBS[:2],
    )
    test_wallet = ord.create_test_wallet("test")
    supply = Decimal("1000")
    rune_a, rune_b = rune_factory(
        "AAAAAA",
        "BBBBBB",
        receiver=multisig.change_address,
        supply=supply,
        divisibility=18,
    )

    assert test_wallet.get_rune_balance_decimal(rune_a) == 0
    assert test_wallet.get_rune_balance_decimal(rune_b) == 0
    assert to_decimal(multisig.get_rune_balance(rune_a), 18) == supply
    assert to_decimal(multisig.get_rune_balance(rune_b), 18) == supply

    transfer_amount = Decimal("123")
    unsigned_psbt = multisig.create_rune_psbt(
        transfers=[
            RuneTransfer(
                rune=rune_a,
                amount=to_base_units(transfer_amount, 18),
                receiver=test_wallet.get_receiving_address(),
            ),
        ]
    )
    signed_psbt = multisig.sign_psbt(unsigned_psbt, finalize=True)
    multisig.broadcast_psbt(signed_psbt)
    ord.mine_and_sync(bitcoind)

    assert test_wallet.get_rune_balance_decimal(rune_a) == transfer_amount
    assert test_wallet.get_rune_balance_decimal(rune_b) == 0
    assert to_decimal(multisig.get_rune_balance(rune_a), 18) == supply - transfer_amount
    assert to_decimal(multisig.get_rune_balance(rune_b), 18) == supply


def test_2_of_3_send_runes(
    ord: OrdService,
    bitcoind: BitcoindService,
    rune_factory,
    multisig_factory,
):
    multisig1 = multisig_factory(
        required=2,
        xpriv=MULTISIG_XPRVS[0],
        xpubs=MULTISIG_XPUBS,
    )
    multisig2 = multisig_factory(
        required=2,
        xpriv=MULTISIG_XPRVS[1],
        xpubs=MULTISIG_XPUBS,
    )
    assert multisig1.change_address == multisig2.change_address

    test_wallet = ord.create_test_wallet("test")
    supply = Decimal("1000")
    rune_a, rune_b = rune_factory(
        "AAAAAA",
        "BBBBBB",
        receiver=multisig1.change_address,
        supply=supply,
        divisibility=18,
    )

    # Sanity check
    assert test_wallet.get_rune_balance_decimal(rune_a) == 0
    assert test_wallet.get_rune_balance_decimal(rune_b) == 0
    for multisig in [multisig1, multisig2]:
        assert to_decimal(multisig.get_rune_balance(rune_a), 18) == supply
        assert to_decimal(multisig.get_rune_balance(rune_b), 18) == supply

    transfer_amount = Decimal("456.7")
    unsigned_psbt = multisig1.create_rune_psbt(
        transfers=[
            RuneTransfer(
                rune=rune_a,
                amount=to_base_units(transfer_amount, 18),
                receiver=test_wallet.get_receiving_address(),
            ),
        ]
    )
    signed1 = multisig1.sign_psbt(unsigned_psbt)
    signed2 = multisig2.sign_psbt(unsigned_psbt)

    with pytest.raises(Exception):
        multisig1.combine_and_finalize_psbt(
            initial_psbt=unsigned_psbt,
            signed_psbts=[signed1],
        )

    finalized_psbt = multisig1.combine_and_finalize_psbt(
        initial_psbt=unsigned_psbt,
        signed_psbts=[signed1, signed2],
    )
    multisig1.broadcast_psbt(finalized_psbt)
    ord.mine_and_sync(bitcoind)

    assert test_wallet.get_rune_balance_decimal(rune_a) == transfer_amount
    assert test_wallet.get_rune_balance_decimal(rune_b) == 0
    for multisig in [multisig1, multisig2]:
        assert to_decimal(multisig.get_rune_balance(rune_a), 18) == supply - transfer_amount
        assert to_decimal(multisig.get_rune_balance(rune_b), 18) == supply


# TODO: test won't use rune outputs for paying for transaction fees
