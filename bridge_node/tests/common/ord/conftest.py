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
        ord.mine_and_sync(bitcoind)

        if receiver:
            for etching in etchings:
                print("SEND", etching.rune)
                root_ord_wallet.send_runes(
                    rune=etching.rune,
                    receiver=receiver,
                    amount=supply,
                )
                ord.mine_and_sync(bitcoind)

                # XXX: there's an ord bug where it complains that output is already locked
                # this should fix it
                bitcoind.cli(f"-rpcwallet={root_ord_wallet.name}", "lockunspent", "true")
                ord.sync_with_bitcoind(bitcoind)

        return [e.rune for e in etchings]

    return create_runes
