import logging
import time

import pytest

from eth_utils import add_0x_prefix
from bridge.evm.utils import load_abi
from bridge.tap.client import Asset
from .utils import wait_for_condition

logger = logging.getLogger(__name__)


TAP_MINT_AMOUNT = 1_000_000
TAP_AMOUNT_DIVISOR = 10**18 // TAP_MINT_AMOUNT


@pytest.fixture(scope='module')
def tap_asset(alice_tap, bob_tap, bitcoin_rpc) -> Asset:
    """
    Mint a new asset from bob, finalize the batch, and return it
    :return:
    """
    try:
        alice_tap.finalize_minting_batch()
    except Exception as e:
        pass
    else:
        bitcoin_rpc.mine_blocks()

    asset = alice_tap.mint_asset(
        name='TestAsset',
        amount=TAP_MINT_AMOUNT,
        finalize=True,
    )
    bitcoin_rpc.mine_blocks()
    bob_tap.sync_universe('alice-tap', issuance_only=True)
    time.sleep(0.5)
    return asset


@pytest.fixture(scope='module')
def evm_token(
    harness,
    alice_web3,
):
    deploy_response = harness.run_hardhat_json_command('deploy-testtoken')
    address = deploy_response['address']
    return alice_web3.eth.contract(
        address,
        abi=load_abi('TestToken'),
    )


@pytest.fixture(scope='module')
def bridgeable_asset(
    owner_bridge_contract,
    alice_web3,
    evm_token,
    tap_asset,
):
    tx1 = owner_bridge_contract.functions.addBridgeableAsset(
        evm_token.address,
        add_0x_prefix(tap_asset.asset_id),
        TAP_AMOUNT_DIVISOR,
        False,
        "TestAsset",
    ).transact()
    tx2 = evm_token.functions.mint(owner_bridge_contract.address, TAP_MINT_AMOUNT * TAP_AMOUNT_DIVISOR).transact()
    alice_web3.eth.wait_for_transaction_receipt(tx1)
    alice_web3.eth.wait_for_transaction_receipt(tx2)
    bridgeable_asset = owner_bridge_contract.functions.assetsByRskTokenAddress(
        evm_token.address
    ).call()
    #print(bridgeable_asset)
    return bridgeable_asset


def test_tap_to_rsk(
    tap_asset,
    alice_tap,
    bob_tap,
    bridge_api,
    bridgeable_asset,
    bitcoin_rpc,
    evm_token,
    user_evm_account,
    owner_bridge_contract,
):
    assert bob_tap.get_asset_balance(tap_asset.asset_id) == 0
    assert evm_token.functions.balanceOf(user_evm_account.address).call() == 0
    assert evm_token.functions.balanceOf(owner_bridge_contract.address).call() == TAP_MINT_AMOUNT * TAP_AMOUNT_DIVISOR

    tap_transfer_amount = 1_000
    bob_initial_address_response = bob_tap.create_address(
        asset_id=tap_asset.asset_id,
        amount=tap_transfer_amount,
    )
    alice_tap.send_assets(bob_initial_address_response.address)
    bitcoin_rpc.mine_blocks()
    wait_for_condition(
        callback=lambda: bob_tap.get_asset_balance(tap_asset.asset_id),
        condition=lambda balance: balance > 0,
        description="bob_tap.get_asset_balance(tap_asset.asset_id) > 0",
    )

    assert bob_tap.get_asset_balance(tap_asset.asset_id) == tap_transfer_amount
    user_deposit_address = bridge_api.generate_tap_deposit_address(
        rsk_address=user_evm_account.address,
        tap_asset_id=tap_asset.asset_id,
        tap_amount=tap_transfer_amount,
    )
    assert user_deposit_address.startswith("taprt1")

    bob_tap.send_assets(user_deposit_address)
    bitcoin_rpc.mine_blocks()

    user_new_balance = wait_for_condition(
        callback=lambda: evm_token.functions.balanceOf(user_evm_account.address).call(),
        condition=lambda balance: balance > 0,
        description="user_new_balance > 0",
    )

    assert user_new_balance == tap_transfer_amount * TAP_AMOUNT_DIVISOR
    assert bob_tap.get_asset_balance(tap_asset.asset_id) == 0
