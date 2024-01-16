import logging
import contextvars
from typing import Literal, Callable, NewType

from anemic.ioc import Container, service
import bitcointx

BTCNetwork = Literal["mainnet", "testnet", "regtest"]
BitcoinTxMonkeyPatcher = NewType("BitcoinTxMonkeyPatcher", Callable[[], None])


logger = logging.getLogger(__name__)


def monkeypatch_bitcointx_network(btc_network: BTCNetwork):
    logger.info("Monkey-patching bitcointx network to %s", btc_network)
    # bitcointx stores the current network in a context variable, and it's used all over the place,
    # such as when initializing address/pubkey classes such as CCoinExtKey.
    # We need to first select it like this:
    _, selected_chain_params = bitcointx.select_chain_params("bitcoin/" + btc_network)
    # And then, because it gets reseted for each thread, and we very much use threads, we also need to monkey-patch
    # the default value:
    bitcointx._chain_params_context._context_vars_storage__["params"] = contextvars.ContextVar(
        "params", default=selected_chain_params
    )


@service(interface_override=BitcoinTxMonkeyPatcher, scope="global")
def bitcoin_tx_monkey_patcher_factory(container: Container):
    from bridge.config import Config

    config = container.get(interface=Config)
    return lambda: monkeypatch_bitcointx_network(config.btc_network)
