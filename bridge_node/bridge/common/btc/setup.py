import contextvars
from typing import Literal

import bitcointx
import bitcointx.util


def setup_bitcointx_network(network: Literal["mainnet", "testnet", "signet", "regtest"]):
    """
    Setup python-bitcointx network so that it works for all threads.

    Python-bitcointx relies on contextvars to set the current network, class dispatchers related to the current network,
    and who knows what kind of special things. These contextvars are inited or module load and changed when
    select_chain_params() is called. New threads will however break the thing because the contextvars are reseted to
    their default values, which is usually the one that corresponds to mainnet, but sometimes None (which will just
    break everything).

    This function essentially monkeypatches the contextvars so that they work for all threads.
    """
    assert network in ["mainnet", "testnet", "signet", "regtest"]

    bitcointx.select_chain_params("bitcoin/" + network)

    for contextvar_compat_instance in [
        bitcointx.util.class_mapping_dispatch_data,
        bitcointx._chain_params_context,
    ]:
        contextvar_dict = contextvar_compat_instance._context_vars_storage__
        values = {k: v.get() for (k, v) in contextvar_dict.items()}
        for var_name, current_value in values.items():
            contextvar_dict[var_name] = contextvars.ContextVar(var_name, default=current_value)
