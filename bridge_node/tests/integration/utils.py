import time
import logging
from decimal import Decimal
from typing import Callable, TypeVar

from web3 import Web3
from eth_utils import to_hex


logger = logging.getLogger(__name__)
T = TypeVar("T")
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_POLL_LATENCY_SECONDS = 5


def to_wei(number, unit="ether"):
    return Web3.to_wei(number, unit)


def from_wei(number, unit="ether"):
    return Web3.from_wei(number, unit)


def wait_for_eth_tx(
    web3: Web3,
    tx_hash,
    *,
    require_success=True,
):
    if isinstance(tx_hash, bytes):
        tx_hash_str = to_hex(tx_hash)
    else:
        tx_hash_str = str(tx_hash)
    logger.info("Waiting for transaction receipt: %s", tx_hash_str)
    receipt = web3.eth.wait_for_transaction_receipt(
        tx_hash,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        poll_latency=DEFAULT_POLL_LATENCY_SECONDS,
    )
    if require_success:
        assert receipt.status == 1, f"Transaction failed: {receipt}"
    return receipt


def to_satoshi(number):
    return int(number * 10**8)


def from_satoshi(number):
    return Decimal(number) / 10**8


def wait_for_condition(
    callback: Callable[[], T],
    condition: Callable[[T], bool],
    description: str = None,
) -> T:
    if not description:
        description = str(condition)
    start = time.time()
    while True:
        value = callback()
        if condition(value):
            return value
        time_waited = time.time() - start
        if time_waited > DEFAULT_TIMEOUT_SECONDS:
            raise TimeoutError(f"Timeout while waiting for condition: {description}")
        logger.info(
            "Waiting for condition: %s, time waited: %.2f s (timeout %.2f s)",
            description,
            time_waited,
            DEFAULT_TIMEOUT_SECONDS,
        )
        time.sleep(DEFAULT_POLL_LATENCY_SECONDS)
