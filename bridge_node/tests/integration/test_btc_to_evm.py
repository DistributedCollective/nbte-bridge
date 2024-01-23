import logging
from decimal import Decimal

import pytest

from .constants import MULTISIG_ADDRESS
from .utils import to_wei, wait_for_condition

logger = logging.getLogger(__name__)


def test_generate_deposit_address(
    user_account,
    bridge_api,
):
    deposit_address = bridge_api.generate_deposit_address(user_account.address)
    assert deposit_address.startswith("bcrt1")


@pytest.mark.skip
def test_btc_to_evm(
    user_web3,
    user_account,
    user_bridge_contract,
    user_bitcoin_rpc,
    bridge_api,
):
    assert user_web3.eth.get_balance(user_account.address) == to_wei(1)
    user_bitcoin_address = user_bitcoin_rpc.getnewaddress()
    transfer_value = Decimal("0.1")
    user_btc_balance_before = user_bitcoin_rpc.getbalance()
    user_evm_balance_before_wei = user_web3.eth.get_balance(user_account.address)
    if user_btc_balance_before < transfer_value * 2:  # some leeway for fees
        user_bitcoin_rpc.generatetoaddress(1, user_bitcoin_address)
        user_bitcoin_rpc.generatetoaddress(101, MULTISIG_ADDRESS)
        wait_for_condition(
            callback=user_bitcoin_rpc.getbalance,
            condition=lambda balance: balance != user_btc_balance_before,
            description="mining initial btc balance for user",
        )

    deposit_address = bridge_api.generate_deposit_address(user_account.address)
    user_bitcoin_rpc.sendtoaddress(
        deposit_address,
        str(transfer_value),
        "",  # comment
        "",  # commentto
        False,  # subtractfeefromamount
        True,  # replaceable
        None,  # conf_target
        "unset",  # estimate_mode
        False,  # avoid reuse
        1,  # fee_rate (sat/vbyte)
    )

    user_evm_balance_after_wei = wait_for_condition(
        callback=lambda: user_web3.eth.get_balance(user_account.address),
        condition=lambda balance: balance != user_evm_balance_before_wei,
        description="user_evm_balance_after_wei != user_evm_balance_before_wei",
    )
    assert user_evm_balance_after_wei == user_evm_balance_before_wei + to_wei(transfer_value)
