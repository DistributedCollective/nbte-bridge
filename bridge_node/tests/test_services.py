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


def test_hardhat_snapshot(hardhat):
    block_number = hardhat.web3.eth.block_number
    snapshot_id = hardhat.snapshot()
    assert isinstance(snapshot_id, str)
    assert len(snapshot_id) > 0

    hardhat.mine(6)
    assert hardhat.web3.eth.block_number != block_number

    hardhat.revert(snapshot_id)
    assert hardhat.web3.eth.block_number == block_number
