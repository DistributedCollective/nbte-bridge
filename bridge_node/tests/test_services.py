import json


def test_postgres(postgres):
    assert postgres.is_started()


def test_bitcoind(bitcoind):
    assert bitcoind.is_started()
    wallet = bitcoind.create_test_wallet()
    resp = bitcoind.cli("listwallets")
    assert isinstance(resp, str)  # we cannot blindly json-parse these
    wallets = json.loads(resp)
    assert isinstance(wallets, list)
    assert wallet.name in wallets
