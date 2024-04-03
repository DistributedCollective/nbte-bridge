import pytest

from tests.services import BitcoindService, OrdService


@pytest.fixture(scope="module")
def root_ord_wallet(ord: OrdService, bitcoind: BitcoindService):
    root = ord.create_test_wallet("root-ord")
    bitcoind.fund_wallets(root)
    return root


@pytest.fixture()
def rune_factory(root_ord_wallet, ord, bitcoind):
    def create_runes(*names, supply=100_000_000, divisibility=18, receiver: str = None):
        etchings = [
            root_ord_wallet.etch_test_rune(
                name,
                supply=supply,
                divisibility=divisibility,
            )
            for name in names
        ]
        ord.mine_and_sync()
        # root_ord_wallet.unlock_unspent()

        if receiver:
            for rune in etchings:
                root_ord_wallet.send_runes(
                    rune=rune,
                    receiver=receiver,
                    amount=supply,
                )
                ord.mine_and_sync()
                # root_ord_wallet.unlock_unspent()

        return etchings

    return create_runes
