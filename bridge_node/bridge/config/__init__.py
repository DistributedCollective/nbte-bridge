import environ
from anemic.ioc import service
import socket
from typing import Literal


@environ.config(prefix="BRIDGE")
class Config:
    node_id = environ.var()
    hostname = environ.var(socket.gethostname())
    port = environ.var(5000, converter=int)
    evm_bridge_contract_address = environ.var()
    evm_rpc_url = environ.var()
    peers = environ.var(converter=lambda s: [x.split("@") for x in s.split(",")])
    btc_network: Literal["mainnet", "testnet", "signet", "regtest"] = environ.var()
    btc_key_derivation_path = environ.var()
    btc_num_required_signers = environ.var(converter=int)

    # TODO: handle secrets properly
    db_url = environ.var()
    evm_private_key = environ.var()  # TODO: should be secret
    btc_rpc_url = (
        environ.var()
    )  # TODO: should be secret, it has the auth in it (or then let's separate auth)
    btc_master_private_key = environ.var()  # TODO: should be secret
    btc_master_public_keys = environ.var(
        converter=lambda s: [x.strip() for x in s.split(",")]
    )  # TODO: should be secret


@service(interface_override=Config, scope="global")
def create_config(_):
    return environ.to_config(Config)
