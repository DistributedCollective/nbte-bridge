import environ
from anemic.ioc import service
import socket


@environ.config(prefix="BRIDGE")
class Config:
    node_id = environ.var()
    hostname = environ.var(socket.gethostname())
    port = environ.var(5000, converter=int)
    evm_bridge_contract_address = environ.var()
    evm_rpc_url = environ.var()
    peers = environ.var(converter=lambda s: [x.split("@") for x in s.split(",")])

    # TODO: handle secrets properly
    evm_private_key = environ.var()  # TODO: should be secret


@service(interface_override=Config, scope="global")
def create_config(_):
    return environ.to_config(Config)
