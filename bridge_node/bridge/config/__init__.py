import json
import logging
import os
import socket
from decimal import Decimal
from getpass import getpass
from typing import Literal

import environ
from anemic.ioc import service

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

    # Rune bridge config
    runes_rune_bridge_contract_address = environ.var()
    runes_evm_rpc_url = environ.var()  # TODO: get rid of this, just use the global one
    runes_evm_default_start_block = environ.var(converter=int, default=1)
    runes_btc_num_required_signers = environ.var(converter=int)
    runes_btc_rpc_wallet_url = environ.var()
    runes_ord_api_url = environ.var()
    runes_btc_base_derivation_path = environ.var(default="m/13/0/0")
    runes_to_evm_fee_percentage_decimal = environ.var(default="0.4", converter=Decimal)

    secret_runes_btc_master_xpubs = environ.var(converter=comma_separated)

    if os.environ.get("BRIDGE_ENCRYPTED_SECRETS", False):
        secrets = wait_for_secrets()

        btc_rpc_url = secrets.get("bridge_btc_rpc_url", environ.var())
        evm_private_key = secrets["bridge_evm_private_key"]

        secret_runes_evm_private_key = secrets["bridge_secret_runes_evm_private_key"]
        secret_runes_btc_master_xpriv = secrets["bridge_secret_runes_btc_master_xpriv"]

        secret_runes_btc_rpc_auth = secrets.get("bridge_secret_runes_btc_rpc_auth", "")
        secret_runes_ord_api_auth = secrets.get("bridge_secret_runes_ord_api_auth", "")
    else:
        logging.warning("Secrets file not found, proceeding without. This should not happen in production.")
        btc_rpc_url = environ.var()  # TODO: should be secret, it has the auth in it (or then let's separate auth)

        # TODO: handle secrets properly
        evm_private_key = environ.var()  # TODO: should be secret

        # Rune bridge secrets
        # TODO: these should be secret
        secret_runes_evm_private_key = environ.var()  # TODO: secret
        secret_runes_btc_master_xpriv = environ.var()
        secret_runes_btc_rpc_auth = environ.var(default="")
        secret_runes_ord_api_auth = environ.var(default="")


@service(interface_override=Config, scope="global")
def create_config(_):
    return environ.to_config(Config)
