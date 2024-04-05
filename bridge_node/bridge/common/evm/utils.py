import logging
import json
import os
import pathlib
import time
from typing import Any, Optional
import eth_utils
from eth_account import Account as EthAccount
from web3 import Web3
from web3.contract.contract import ContractEvent
from web3.middleware import geth_poa_middleware, construct_sign_and_send_raw_middleware
from web3.types import EventData
from web3.gas_strategies.rpc import rpc_gas_price_strategy
from eth_account.account import LocalAccount

THIS_DIR = os.path.dirname(__file__)
ABI_DIR = os.path.join(THIS_DIR, "abi")


logger = logging.getLogger(__name__)


def create_web3(
    rpc_url: str,
    *,
    account: Optional[LocalAccount] = None,
    # we default to rpc_gas_price_strategy because it makes things work on RSK and RSK Testnet,
    # and it works on hardhat too. it also works on ethereum and other chains, though it might be less
    # efficient than other strategies.
    gas_price_strategy=rpc_gas_price_strategy,
) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    # Fix for this (might not be necessary for all chains):
    # web3.exceptions.ExtraDataLengthError:
    # The field extraData is 97 bytes, but should be 32. It is quite likely that  you are connected to a POA chain.
    # Refer to http://web3py.readthedocs.io/en/stable/middleware.html#geth-style-proof-of-authority for more details.
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    w3.eth.set_gas_price_strategy(gas_price_strategy)

    if account:
        w3.middleware_onion.add(construct_sign_and_send_raw_middleware(account))
        w3.eth.default_account = account.address

    return w3


def load_abi(name: str, abi_dir: str | pathlib.Path = ABI_DIR) -> list[dict[str, Any]]:
    abi_path = os.path.join(abi_dir, f"{name}.json")
    if not os.path.abspath(abi_path).startswith(os.path.abspath(abi_dir)):
        raise ValueError(f"Invalid ABI name: {name} (path outside ABI dir {abi_dir})")
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


def to_wei(number, unit="ether"):
    return Web3.to_wei(number, unit)


def from_wei(number, unit="ether"):
    return Web3.from_wei(number, unit)


def recover_message(content, signature):
    return EthAccount.recover_message(
        content,
        signature=signature,
    )


def is_zero_address(address) -> bool:
    canonical = eth_utils.to_canonical_address(address)
    return not any(canonical)
