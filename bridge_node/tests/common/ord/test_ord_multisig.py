import secrets
from decimal import Decimal

import pytest
from bridge.common.ord.multisig import OrdMultisig
from bridge.common.ord.transfers import RuneTransfer
from bridge.common.utils import to_base_units, to_decimal
from bitcointx.wallet import CCoinExtKey
from tests.services import BitcoindService, OrdService, OrdWallet

DEFAULT_KEY_DERIVATION_PATH = "m/0/0"


@pytest.fixture()
def multisig_factory(
    bitcoind: BitcoindService,
    ord: OrdService,
):
    def _create_multisig(
        required: int,
        xpriv: str,
        xpubs: list[str],
        base_derivation_path: str = DEFAULT_KEY_DERIVATION_PATH,
        *,
        fund: bool = True,
    ):
        wallet = bitcoind.create_test_wallet(
            prefix=f"ord-multisig-{required}-of-{len(xpubs)}",
            blank=True,
            disable_private_keys=True,
        )
        multisig = OrdMultisig(
            master_xpriv=xpriv,
            master_xpubs=xpubs,
            num_required_signers=required,
            base_derivation_path=base_derivation_path,
            bitcoin_rpc=wallet.rpc,
            ord_client=ord.api_client,
        )
        multisig.import_descriptors_to_bitcoind(
            range=100,
        )
        if fund:
            bitcoind.fund_addresses(multisig.change_address)
        return multisig

    def create_multisigs(
        required: int,
        num_signers: int,
        base_derivation_path: str = DEFAULT_KEY_DERIVATION_PATH,
        *,
        fund: bool = True,
    ):
        assert num_signers >= required
        assert required >= 1

        xprivs = [CCoinExtKey.from_seed(secrets.token_bytes(64)) for _ in range(num_signers)]
        xpubs = [xpriv.neuter() for xpriv in xprivs]
        multisigs = [
            _create_multisig(
                required=required,
                xpriv=str(xpriv),
                xpubs=[str(xpub) for xpub in xpubs],
                base_derivation_path=base_derivation_path,
                fund=False,
            )
            for xpriv in xprivs
        ]
        assert (
            len({m.change_address for m in multisigs}) == 1
        ), "all multisigs should have the same change address"
        if fund:
            bitcoind.fund_addresses(multisigs[0].change_address)
        return multisigs

    return create_multisigs


@pytest.fixture()
def multisig(multisig_factory):
    # Default multisig for easier testing
    return multisig_factory(
        num_signers=3,
        required=2,
    )[0]


def test_verify_descriptor(
    multisig,
    bitcoind,
):
    derived_addresses = bitcoind.rpc.call("deriveaddresses", multisig.get_descriptor(), [0, 0])
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
    multisig, _ = multisig_factory(
        required=1,
        num_signers=2,
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
    multisig1, multisig2, _ = multisig_factory(
        required=2,
        num_signers=3,
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


def test_ord_multisig_send_runes_from_derived_address(
    ord: OrdService,
    bitcoind: BitcoindService,
    root_ord_wallet: OrdWallet,
    multisig_factory,
):
    test_wallet = ord.create_test_wallet("derived-receiver")
    multisig, _ = multisig_factory(
        required=1,
        num_signers=2,
    )
    supply = Decimal("1234")
    etching = root_ord_wallet.etch_test_rune("DERIVEDTEST", supply=supply)
    ord.mine_and_sync(bitcoind)

    # Sanity check
    assert to_decimal(multisig.get_rune_balance(etching.rune), 18) == 0
    assert test_wallet.get_rune_balance_decimal(etching.rune) == 0

    derived_address = multisig.derive_address(42)
    assert derived_address != multisig.change_address

    root_ord_wallet.send_runes(
        rune=etching.rune,
        receiver=derived_address,
        amount=supply,
    )
    ord.mine_and_sync(bitcoind)

    assert to_decimal(multisig.get_rune_balance(etching.rune), 18) == supply

    transfer_amount = Decimal("98.7")
    multisig.send_runes(
        transfers=[
            RuneTransfer(
                rune=etching.rune,
                receiver=test_wallet.get_receiving_address(),
                amount=to_base_units(transfer_amount, 18),
            )
        ],
    )
    ord.mine_and_sync(bitcoind)

    assert to_decimal(multisig.get_rune_balance(etching.rune), 18) == supply - transfer_amount
    assert test_wallet.get_rune_balance_decimal(etching.rune) == transfer_amount


# TODO: test won't use rune outputs for paying for transaction fees
