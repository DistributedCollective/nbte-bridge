from decimal import Decimal

import pytest
from bridge.btc.rpc import BitcoinRPC
from .constants import USER_BITCOIN_RPC_URL


@pytest.fixture()
def rpc():
    return BitcoinRPC(USER_BITCOIN_RPC_URL)


def test_getbalance(rpc):
    ret = rpc.getbalance()
    assert isinstance(ret, Decimal)
    assert ret >= 0


# TODO: test moar
