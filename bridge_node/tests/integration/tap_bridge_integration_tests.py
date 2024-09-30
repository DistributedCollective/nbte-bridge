import logging
import time

import pytest
from eth_utils import add_0x_prefix

from bridge.common.evm.utils import load_abi
from bridge.common.tap.client import Asset

from .utils import wait_for_condition

logger = logging.getLogger(__name__)


TAP_MINT_AMOUNT = 1_000_000
TAP_AMOUNT_DIVISOR = 10**18 // TAP_MINT_AMOUNT


def sync_universes_against_leader(leader_tap, tap_nodes):
    for tap_node in tap_nodes:
        if tap_node is leader_tap:
            continue
        tap_node.sync_universe(leader_tap.public_universe_host, issuance_only=True)


@pytest.fixture()
def tap_asset(alice_tap, tap_nodes, bitcoin_rpc) -> Asset:
    """
    Mint a new asset from bob, finalize the batch, and return it
    :return:
    """
    try:
        alice_tap.finalize_minting_batch()
    except Exception:
        pass
    else:
        bitcoin_rpc.mine_blocks()

    asset = alice_tap.mint_asset(
        name="TestAsset",
        amount=TAP_MINT_AMOUNT,
        finalize=True,
    )
    bitcoin_rpc.mine_blocks()
    sync_universes_against_leader(alice_tap, tap_nodes)
    time.sleep(0.5)
    return asset


@pytest.fixture()
def evm_token(
    harness,
    alice_web3,
):
    deploy_response = harness.run_hardhat_json_command("deploy-testtoken")
    address = deploy_response["address"]
    return alice_web3.eth.contract(
        address,
        abi=load_abi("TestToken"),
    )


@pytest.fixture()
def user_evm_token(
    user_web3,
    evm_token,
):
    return user_web3.eth.contract(
        evm_token.address,
        abi=evm_token.abi,
    )


@pytest.fixture()
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
    bridgeable_asset = owner_bridge_contract.functions.assetsByRskTokenAddress(evm_token.address).call()
    # print(bridgeable_asset)
    return bridgeable_asset


# TODO: don't skip if the TAP bridge is eventually implemented
@pytest.mark.skip
def test_integration_tap_to_rsk(
    tap_asset,
    alice_tap,
    user_tap,
    bridge_api,
    bridgeable_asset,
    bitcoin_rpc,
    evm_token,
    user_evm_account,
    owner_bridge_contract,
):
    assert user_tap.get_asset_balance(tap_asset.asset_id) == 0
    assert evm_token.functions.balanceOf(user_evm_account.address).call() == 0
    initial_bridge_balance = evm_token.functions.balanceOf(owner_bridge_contract.address).call()

    tap_transfer_amount = 1_000
    user_initial_address_response = user_tap.create_address(
        asset_id=tap_asset.asset_id,
        amount=tap_transfer_amount,
    )
    alice_tap.send_assets(user_initial_address_response.address)

    bitcoin_rpc.mine_blocks()
    wait_for_condition(
        callback=lambda: user_tap.get_asset_balance(tap_asset.asset_id),
        condition=lambda balance: balance > 0,
        description="user_tap.get_asset_balance(tap_asset.asset_id) > 0",
    )

    assert user_tap.get_asset_balance(tap_asset.asset_id) == tap_transfer_amount
    user_deposit_address = bridge_api.generate_tap_deposit_address(
        rsk_address=user_evm_account.address,
        tap_asset_id=tap_asset.asset_id,
        tap_amount=tap_transfer_amount,
    )
    assert user_deposit_address.startswith("taprt1")

    user_tap.send_assets(user_deposit_address)
    bitcoin_rpc.mine_blocks()

    user_new_balance = wait_for_condition(
        callback=lambda: evm_token.functions.balanceOf(user_evm_account.address).call(),
        condition=lambda balance: balance > 0,
        description="user_new_balance > 0",
    )

    assert user_new_balance == tap_transfer_amount * TAP_AMOUNT_DIVISOR
    assert evm_token.functions.balanceOf(owner_bridge_contract.address).call() == (
        initial_bridge_balance - tap_transfer_amount * TAP_AMOUNT_DIVISOR
    )
    assert user_tap.get_asset_balance(tap_asset.asset_id) == 0

    wait_for_condition(
        callback=lambda: bridge_api.get_transfers(user_deposit_address, "tap_to_rsk"),
        condition=lambda transfers: transfers[0]["status"] == "finalized",
        description="transfer status == finalized",
    )

    transfers = bridge_api.get_transfers(user_deposit_address, "tap_to_rsk")

    assert len(transfers) == 1
    assert transfers[0]["status"] == "finalized"
    assert transfers[0]["address"] == user_deposit_address
    assert transfers[0]["id"] == 1


# TODO: don't skip if the TAP bridge is eventually implemented
@pytest.mark.skip
def test_integration_rsk_to_tap(
    tap_asset,
    alice_tap,
    user_tap,
    bridge_api,
    bridgeable_asset,
    bitcoin_rpc,
    evm_token,
    user_evm_token,
    user_evm_account,
    user_bridge_contract,
    user_web3,
):
    assert user_tap.get_asset_balance(tap_asset.asset_id) == 0

    tap_transfer_amount = 1_000
    rsk_transfer_amount = tap_transfer_amount * TAP_AMOUNT_DIVISOR
    initial_bridge_balance = evm_token.functions.balanceOf(user_bridge_contract.address).call()
    assert initial_bridge_balance > rsk_transfer_amount

    evm_token.functions.mint(user_evm_account.address, rsk_transfer_amount).transact()
    user_rsk_balance = wait_for_condition(
        callback=lambda: evm_token.functions.balanceOf(user_evm_account.address).call(),
        condition=lambda balance: balance > 0,
        description="evm_token.functions.balanceOf(user_evm_account.address).call() > 0",
    )
    assert user_rsk_balance == rsk_transfer_amount

    receiver_address_response = user_tap.create_address(
        asset_id=tap_asset.asset_id,
        amount=tap_transfer_amount,
    )

    tx_hash = user_evm_token.functions.approve(user_bridge_contract.address, rsk_transfer_amount).transact(
        {
            "gas": 100_000,
        }
    )
    receipt = user_web3.eth.wait_for_transaction_receipt(tx_hash, poll_latency=2)
    assert receipt.status

    tx_hash = user_bridge_contract.functions.transferToTap(
        receiver_address_response.address,
    ).transact(
        {
            "gas": 2_000_000,
        }
    )
    receipt = user_web3.eth.wait_for_transaction_receipt(tx_hash, poll_latency=2)
    assert receipt.status
    assert evm_token.functions.balanceOf(user_evm_account.address).call() == 0
    assert evm_token.functions.balanceOf(user_bridge_contract.address).call() == (
        initial_bridge_balance + rsk_transfer_amount
    )

    def callback():
        bitcoin_rpc.mine_blocks(2)
        return user_tap.get_asset_balance(tap_asset.asset_id)

    user_tap_balance = wait_for_condition(
        callback=callback,
        condition=lambda balance: balance > 0,
        description="user_tap.get_asset_balance(tap_asset.asset_id) > 0",
    )

    assert user_tap_balance == tap_transfer_amount

    wait_for_condition(
        callback=lambda: bridge_api.get_transfers(user_evm_account.address, "rsk_to_tap"),
        condition=lambda transfers: transfers[0]["status"] == "finalized",
        description="transfer status == finalized",
    )

    transfers = bridge_api.get_transfers(user_evm_account.address, "rsk_to_tap")

    assert len(transfers) == 1
    assert transfers[0]["status"] == "finalized"
    assert transfers[0]["address"] == user_evm_account.address
    assert transfers[0]["id"] == 1
