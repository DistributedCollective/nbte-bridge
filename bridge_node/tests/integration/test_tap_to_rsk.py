import logging
from decimal import Decimal

import pytest

from bridge.api_client import BridgeAPIClient
from .utils import to_wei, wait_for_condition

logger = logging.getLogger(__name__)


# @pytest.fixture()
# def bridgeable_asset(bridge_evm_contract: )
#     pass
#
# def test_generate_deposit_address(
#     user_account,
#     bridge_api: BridgeAPIClient,
# ):
#     deposit_address = bridge_api.generate_tap_deposit_address(
#         user_rsk_address=user_account.address
#     )
#     assert deposit_address.startswith("bcrt1")


def test_tap_to_rsk(
    harness,
    user_web3,
    user_account,
    user_bridge_contract,
    bridge_api,
):
    print("OK")
