from decimal import Decimal

from .utils import from_satoshi, to_wei, wait_for_condition, wait_for_eth_tx


def test_evm_to_btc(
    user_web3,
    user_account,
    user_bridge_contract,
    user_bitcoin_rpc,
):
    assert user_web3.eth.get_balance(user_account.address) == to_wei(1)
    user_satoshis_before = user_bitcoin_rpc.getbalance()
    bitcoin_address = user_bitcoin_rpc.getnewaddress()
    transfer_value = Decimal("0.1")

    tx_hash = user_bridge_contract.functions.transferToBtc(
        str(bitcoin_address),
    ).transact(
        {
            "from": user_account.address,
            "value": to_wei(transfer_value),
        }
    )
    wait_for_eth_tx(user_web3, tx_hash)

    user_satoshis_after = wait_for_condition(
        callback=user_bitcoin_rpc.getbalance,
        condition=lambda newsat: newsat != user_satoshis_before,
        description="user_satoshis_after != user_satoshis_before",
    )

    assert (
        from_satoshi(user_satoshis_after) == from_satoshi(user_satoshis_before) + transfer_value
    ), "User BTC balance changed, but not by the expected amount"
