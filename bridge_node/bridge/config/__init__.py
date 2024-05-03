import json
import logging
import socket
from getpass import getpass
from typing import Literal

import environ
from anemic.ioc import service

from .secrets import secret

logger = logging.getLogger(__name__)


def wait_for_secrets():
    """
    Wait for the user to provide decrypted secrets as a single-line JSON string.
    In practice, this should be done by running server/serve_with_secrets.py.

    Requires the BRIDGE_ENCRYPTED_SECRETS environment variable to be set to 1.
    """
    try:
        return json.loads(getpass("Provide decrypted secrets: "))
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON provided: {e}")
        exit(1)


def comma_separated(s: str):
    return [x.strip() for x in s.split(",") if x.strip()]


@environ.config(prefix="BRIDGE")
class Config:
    node_id = environ.var()
    hostname = environ.var(socket.gethostname())
    leader_node_id = environ.var()
    port = environ.var(5000, converter=int)
    peers = environ.var(converter=lambda s: [x.split("@") for x in comma_separated(s)])
    db_url = environ.var()
    enabled_bridges = environ.var(converter=comma_separated, default="all")
    access_control_contract_address = environ.var()
    evm_rpc_url = environ.var()

    # Generic blockchain settings for all bridges
    evm_block_safety_margin = environ.var(converter=int, default=5)
    btc_network: Literal["mainnet", "testnet", "signet", "regtest"] = environ.var()
    btc_min_confirmations = environ.var(converter=int, default=1)
    btc_listsinceblock_buffer = environ.var(converter=int, default=6)

    # Tap bridge config.
    # TODO: prefix these!
    evm_bridge_contract_address = environ.var()
    evm_start_block = environ.var(converter=int, default=1)
    tap_host = environ.var()
    tap_macaroon_path = environ.var()
    tap_tls_cert_path = environ.var()

    # TODO: this global btc rpc url is not needed
    btc_rpc_url = secret("bridge_btc_rpc_url", environ.var())
    evm_private_key = secret("bridge_evm_private_key")

    # Messenger settings
    discord_webhook_url = environ.var(default="")
    slack_webhook_url = environ.var(default="")
    slack_webhook_channel = environ.var(default="")


@service(interface_override=Config, scope="global")
def create_config(_):
    return environ.to_config(Config)
