import typing
import bitcointx
import bitcointx.rpc
from anemic.ioc import Container, service

from ..config import Config

BitcoinRPC = typing.NewType("BitcoinRPC", bitcointx.rpc.RPCCaller)


@service(interface_override=BitcoinRPC, scope="global")
def bitcoin_rpc_factory(container: Container):
    config = container.get(interface=Config)

    # NOTE: bitcoin network needs to be configured somewhere, and it's a global var (well, threadlocal)
    # let's do it here... but it also means that all bitcoin operations will fail until this factory
    # is called
    bitcointx.select_chain_params("bitcoin/" + config.btc_network)

    return bitcointx.rpc.RPCCaller(config.btc_rpc_url)
