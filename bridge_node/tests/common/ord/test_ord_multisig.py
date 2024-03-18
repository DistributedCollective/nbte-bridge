from decimal import Decimal

import pytest
from bridge.common.ord.multisig import OrdMultisig
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
    ):
        wallet = bitcoind.create_test_wallet(
            prefix=f"ord-multisig-{required}-of-{len(xpubs)}",
            watchonly=True,
        )
        multisig = OrdMultisig(
            master_xpriv=MULTISIG_XPRVS[0],
            master_xpubs=MULTISIG_XPUBS,
            num_required_signers=2,
            key_derivation_path=MULTISIG_KEY_DERIVATION_PATH,
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

    assert multisig.get_rune_balance(rune_a) == 1234 * 10**17
    assert multisig.get_rune_balance(rune_b) == 0


def test_1_of_1_send_runes(
    ord: OrdService,
    bitcoind: BitcoindService,
    rune_factory,
    multisig_factory,
):
    multisig = multisig_factory(
        required=1,
        xpriv=MULTISIG_XPRVS[0],
        xpubs=[MULTISIG_XPUBS[0]],
    )
    test_wallet = ord.create_test_wallet("test")
    supply = Decimal("1000")
    rune_a, rune_b = rune_factory(
        "AAAAAA",
        "BBBBBB",
        receiver=multisig.change_address,
        supply=supply,
    )

    assert test_wallet.get_rune_balance_decimal(rune_a) == 0
    assert test_wallet.get_rune_balance_decimal(rune_b) == 0
    assert multisig.get_rune_balance(rune_a) == int(supply * 10**18)
    assert multisig.get_rune_balance(rune_b) == int(supply * 10**18)

    # TODO: finish this
