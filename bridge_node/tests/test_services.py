def test_postgres(postgres):
    assert postgres.is_started()


def test_bitcoind(bitcoind):
    assert bitcoind.is_started()
    assert bitcoind.cli("listwallets") == []
