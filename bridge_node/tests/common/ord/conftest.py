import secrets

import pytest
from bitcointx.wallet import (
    CCoinExtKey,
)

from bridge.common.ord.multisig import OrdMultisig
from tests.services import BitcoindService, OrdService

DEFAULT_KEY_DERIVATION_PATH = "m/0/0"


@pytest.fixture(scope="module")
def root_ord_wallet(ord: OrdService, bitcoind: BitcoindService):  # noqa A002
    root = ord.create_test_wallet("root-ord")
    bitcoind.fund_wallets(root)
    return root


@pytest.fixture(scope="module")
def rune_factory(root_ord_wallet, ord, bitcoind):  # noqa A002
    def create_runes(*names, supply=100_000_000, divisibility=18, receiver: str = None):
        etchings = [
            root_ord_wallet.etch_test_rune(
                name,
                supply=supply,
                divisibility=divisibility,
            )
            for name in names
        ]
        # root_ord_wallet.unlock_unspent()

        if receiver:
            for etching in etchings:
                root_ord_wallet.send_runes(
                    rune=etching.rune,
                    receiver=receiver,
                    amount_decimal=supply,
                )
                ord.mine_and_sync()
                # root_ord_wallet.unlock_unspent()

        return [e.rune for e in etchings]

    return create_runes


@pytest.fixture(scope="module")
def multisig_factory(
    bitcoind: BitcoindService,
    ord: OrdService,  # noqa A002
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
            btc_wallet_name=wallet.name,
        )
        multisig.import_descriptors_to_bitcoind(
            desc_range=100,
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
        assert len({m.change_address for m in multisigs}) == 1, "all multisigs should have the same change address"
        if fund:
            bitcoind.fund_addresses(multisigs[0].change_address)
        return multisigs

    return create_multisigs
