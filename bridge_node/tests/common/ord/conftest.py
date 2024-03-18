import pytest


@pytest.fixture(scope="module")
def root_ord_wallet(ord, bitcoind):
    root = ord.create_test_wallet("root")
    bitcoind.fund_wallets(root)
    return root


@pytest.fixture()
def rune_factory(root_ord_wallet, ord, bitcoind):
    def create_runes(*names):
        etchings = [root_ord_wallet.etch_test_rune(name) for name in names]
        ord.mine_and_sync(bitcoind)
        return [e.rune for e in etchings]

    return create_runes
