import typing
import bitcointx
import bitcointx.rpc
from anemic.ioc import Container, service

from ..config import Config

BitcoinRPC = typing.NewType("BitcoinRPC", bitcointx.rpc.RPCCaller)


@service(interface_override=BitcoinRPC, scope="global")
def bitcoin_rpc_factory(container: Container):
    config = container.get(interface=Config)

    return bitcointx.rpc.RPCCaller(config.btc_rpc_url)
