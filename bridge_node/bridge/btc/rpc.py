import typing
import bitcoin
import bitcoin.rpc
from anemic.ioc import Container, service

from ..config import Config

BitcoinRPC = typing.NewType("BitcoinRPC", bitcoin.rpc.Proxy)


@service(interface_override=BitcoinRPC, scope="global")
def bitcoin_rpc_factory(container: Container):
    config = container.get(interface=Config)

    # NOTE: bitcoin network needs to be configured somewhere, and it's a global var
    # let's do it here... but it also means that all bitcoin operations will fail until this factory
    # is called
    bitcoin.SelectParams(config.btc_network)

    return bitcoin.rpc.Proxy(config.btc_rpc_url)
