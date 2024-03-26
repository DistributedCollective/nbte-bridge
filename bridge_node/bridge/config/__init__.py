import environ
from anemic.ioc import service
import socket
from typing import Literal


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
    enabled_bridges = environ.var(converter=comma_separated, default=["all"])

    # Generic blockchain settings for all bridges
    evm_block_safety_margin = environ.var(converter=int, default=5)
    btc_network: Literal["mainnet", "testnet", "signet", "regtest"] = environ.var()

    # Tap bridge config.
    # TODO: prefix these!
    evm_bridge_contract_address = environ.var()
    evm_rpc_url = environ.var()
    evm_start_block = environ.var(converter=int, default=1)
    tap_host = environ.var()
    tap_macaroon_path = environ.var()
    tap_tls_cert_path = environ.var()
    # TODO: handle secrets properly
    evm_private_key = environ.var()  # TODO: should be secret
    btc_rpc_url = (
        environ.var()
    )  # TODO: should be secret, it has the auth in it (or then let's separate auth)

    # Rune bridge config
    runes_rune_bridge_contract_address = environ.var()
    runes_evm_rpc_url = environ.var()
    runes_evm_default_start_block = environ.var(converter=int, default=1)
    runes_btc_rpc_wallet_url = environ.var()
    runes_ord_api_url = environ.var()
    runes_btc_base_derivation_path = environ.var(default="m/13/0/0")

    # Rune bridge secrets
    # TODO: these should be secret
    secret_runes_evm_private_key = environ.var()  # TODO: secret
    secret_runes_btc_master_xpriv = environ.var()
    secret_runes_btc_master_xpubs = environ.var(converter=comma_separated)
    secret_runes_btc_rpc_auth = environ.var(default="")
    secret_runes_ord_api_auth = environ.var(default="")


@service(interface_override=Config, scope="global")
def create_config(_):
    return environ.to_config(Config)
