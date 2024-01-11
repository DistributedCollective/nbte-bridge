import logging
import json
import os
import time
from typing import Any, Optional
from web3 import Web3
from web3.contract.contract import ContractEvent
from web3.middleware import geth_poa_middleware, construct_sign_and_send_raw_middleware
from web3.types import EventData
from eth_account.account import LocalAccount

THIS_DIR = os.path.dirname(__file__)
ABI_DIR = os.path.join(THIS_DIR, "abi")


logger = logging.getLogger(__name__)


def create_web3(
    rpc_url: str,
    *,
    account: Optional[LocalAccount] = None,
) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    # Fix for this (might not be necessary for all chains):
    # web3.exceptions.ExtraDataLengthError:
    # The field extraData is 97 bytes, but should be 32. It is quite likely that  you are connected to a POA chain.
    # Refer to http://web3py.readthedocs.io/en/stable/middleware.html#geth-style-proof-of-authority for more details.
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    if account:
        w3.middleware_onion.add(construct_sign_and_send_raw_middleware(account))
        w3.eth.default_account = account.address

    # TODO: gas price strategy (rollup might not support new-style transactions)

    return w3


def load_abi(name: str) -> list[dict[str, Any]]:
    abi_path = os.path.join(ABI_DIR, f"{name}.json")
    if not os.path.abspath(abi_path).startswith(os.path.abspath(ABI_DIR)):
        raise ValueError(f"Invalid ABI name: {name} (path outside ABI dir {ABI_DIR})")
    with open(abi_path) as f:
        return json.load(f)


def get_events(
    *,
    event: ContractEvent,
    from_block: int,
    to_block: int,
    batch_size: int = 100,
    argument_filters=None,
) -> list[EventData]:
    """Load events in batches"""
    if to_block < from_block:
        raise ValueError(f"to_block {to_block} is smaller than from_block {from_block}")

    logger.info(
        "fetching events from %s to %s with batch size %s", from_block, to_block, batch_size
    )
    ret = []
    batch_from_block = from_block
    while batch_from_block <= to_block:
        batch_to_block = min(batch_from_block + batch_size, to_block)
        logger.info(
            "fetching batch from %s to %s (up to %s)", batch_from_block, batch_to_block, to_block
        )

        events = get_event_batch_with_retries(
            event=event,
            from_block=batch_from_block,
            to_block=batch_to_block,
            argument_filters=argument_filters,
        )
        if len(events) > 0:
            logger.info("found %s events in batch", len(events))
        ret.extend(events)
        batch_from_block = batch_to_block + 1
    logger.info("found %s events in total", len(ret))
    return ret


def get_event_batch_with_retries(
    event: ContractEvent,
    from_block: int,
    to_block: int,
    *,
    argument_filters=None,
    retries=10,
):
    while True:
        try:
            return event.get_logs(
                fromBlock=from_block,
                toBlock=to_block,
                argument_filters=argument_filters,
            )
        except Exception as e:
            if retries <= 0:
                raise e
            logger.warning("error in get_all_entries: %s, retrying (%s)", e, retries)
            retries -= 1


def exponential_sleep(attempt, max_sleep_time=256.0):
    sleep_time = min(2**attempt, max_sleep_time)
    time.sleep(sleep_time)
