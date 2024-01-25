import logging
from decimal import Decimal

from .utils import evm_mine_blocks, to_wei, wait_for_condition, wait_for_eth_tx


logger = logging.getLogger(__name__)


def test_evm_to_btc(
    user_web3,
    user_account,
    user_bridge_contract,
    user_bitcoin_rpc,
):
    assert user_web3.eth.get_balance(user_account.address), "sanity check, user has no balance"
    user_btc_before = user_bitcoin_rpc.getbalance()
    bitcoin_address = user_bitcoin_rpc.getnewaddress()
    logger.info("User btc address: %s", bitcoin_address)
    transfer_value = Decimal("0.1")

    tx_hash = user_bridge_contract.functions.transferToBtc(
        str(bitcoin_address),
    ).transact(
        {
            "from": user_account.address,
            "value": to_wei(transfer_value),
        }
    )
    evm_mine_blocks(user_web3, 5)  # Mine blocks to make it confirm faster
    receipt = wait_for_eth_tx(user_web3, tx_hash)
    assert receipt.status, "Transaction failed"

    user_btc_after = wait_for_condition(
        callback=user_bitcoin_rpc.getbalance,
        condition=lambda balance: balance != user_btc_before,
        description="user_satoshis_after != user_satoshis_before",
    )

    assert (
        user_btc_after == user_btc_before + transfer_value
    ), "User BTC balance changed, but not by the expected amount"
