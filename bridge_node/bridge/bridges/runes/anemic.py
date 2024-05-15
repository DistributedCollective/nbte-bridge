# This file is here because certain places (MainBridge, views...)
# want to have RuneBridge and RuneBridgeService in the IoC container
# Maybe we should just have manual wiring everywhere?
from decimal import Decimal

import environ
from anemic.ioc import (
    Container,
    service,
)

from ...common.messengers import Messenger
from ...common.p2p.network import Network
from ...common.services.transactions import TransactionManager
from ...config import Config, comma_separated
from ...config.secrets import secret
from .bridge import RuneBridge
from .config import (
    RuneBridgeConfig,
    RuneBridgeSecrets,
)
from .service import RuneBridgeService
from .wiring import (
    RuneBridgeWiring,
    wire_rune_bridge,
)


def create_rune_bridge_env_config(
    prefix: str,
):
    @environ.config(prefix=f"BRIDGE_{prefix}".upper())
    class RuneBridgeEnvConfig:
        # Rune bridge config
        rune_bridge_contract_address = environ.var()
        evm_rpc_url = environ.var()
        evm_default_start_block = environ.var(converter=int, default=1)
        evm_block_safety_margin = environ.var(converter=int)
        btc_num_required_signers = environ.var(converter=int)
        btc_rpc_wallet_url = environ.var()
        ord_api_url = environ.var()
        btc_base_derivation_path = environ.var()
        to_evm_fee_percentage_decimal = environ.var(default="0.4", converter=Decimal)
        btc_max_fee_rate_sats_per_vbyte = environ.var(default="300", converter=int)
        btc_min_postage_sat = environ.var(default="10000", converter=int)

    @environ.config(prefix=f"BRIDGE_SECRET_{prefix}".upper())
    class RuneBridgeEnvSecrets:
        btc_master_xpubs = environ.var(converter=comma_separated)

        evm_private_key = secret(f"bridge_secret_{prefix}_evm_private_key")
        btc_master_xpriv = secret(f"bridge_secret_{prefix}_btc_master_xpriv")

        btc_rpc_auth = secret(f"bridge_secret_{prefix}_btc_rpc_auth", "")
        ord_api_auth = secret(f"bridge_secret_{prefix}_ord_api_auth", "")

    runes_env = environ.to_config(RuneBridgeEnvConfig)
    secrets_env = environ.to_config(RuneBridgeEnvSecrets)
    return runes_env, secrets_env


def wire_rune_bridge_from_environ(
    *,
    bridge_name: str,
    environ_prefix: str,
    container: Container,
):
    global_config = container.get(interface=Config)
    runes_env, secrets_env = create_rune_bridge_env_config(environ_prefix)
    return wire_rune_bridge(
        config=RuneBridgeConfig(
            bridge_id=bridge_name,
            btc_network=global_config.btc_network,
            btc_min_confirmations=global_config.btc_min_confirmations,
            btc_listsinceblock_buffer=global_config.btc_listsinceblock_buffer,
            evm_block_safety_margin=runes_env.evm_block_safety_margin,
            rune_bridge_contract_address=runes_env.rune_bridge_contract_address,
            evm_rpc_url=runes_env.evm_rpc_url,
            btc_rpc_wallet_url=runes_env.btc_rpc_wallet_url,
            ord_api_url=runes_env.ord_api_url,
            btc_base_derivation_path=runes_env.btc_base_derivation_path,
            btc_num_required_signers=runes_env.btc_num_required_signers,
            evm_default_start_block=runes_env.evm_default_start_block,
            runes_to_evm_fee_percentage_decimal=runes_env.to_evm_fee_percentage_decimal,
            btc_max_fee_rate_sats_per_vbyte=runes_env.btc_max_fee_rate_sats_per_vbyte,
        ),
        secrets=RuneBridgeSecrets(
            evm_private_key=secrets_env.evm_private_key,
            btc_master_xpriv=secrets_env.btc_master_xpriv,
            btc_master_xpubs=secrets_env.btc_master_xpubs,
            btc_rpc_auth=secrets_env.btc_rpc_auth,
            ord_api_auth=secrets_env.ord_api_auth,
        ),
        network=container.get(interface=Network),
        transaction_manager=container.get(interface=TransactionManager),
        messenger=container.get(interface=Messenger),
    )


@service(scope="global", interface_override=RuneBridgeWiring, name="runesrsk-wiring")
def runesrsk_wiring_factory(container: Container):
    return wire_rune_bridge_from_environ(
        bridge_name="runesrsk",
        environ_prefix="runes",
        container=container,
    )


@service(scope="global", interface_override=RuneBridge, name="runesrsk-bridge")
def runesrsk_bridge_factory(container: Container):
    wiring: RuneBridgeWiring = container.get(interface=RuneBridgeWiring, name="runesrsk-wiring")
    return wiring.bridge


@service(scope="global", interface_override=RuneBridgeService, name="runesrsk-service")
def runesrsk_service_factory(container: Container):
    wiring: RuneBridgeWiring = container.get(interface=RuneBridgeWiring, name="runesrsk-wiring")
    return wiring.service


@service(scope="global", interface_override=RuneBridgeWiring, name="runesbob-wiring")
def runesbob_wiring_factory(container: Container):
    return wire_rune_bridge_from_environ(
        bridge_name="runesbob",
        environ_prefix="runesbob",
        container=container,
    )


@service(scope="global", interface_override=RuneBridge, name="runesbob-bridge")
def runesbob_bridge_factory(container: Container):
    wiring: RuneBridgeWiring = container.get(interface=RuneBridgeWiring, name="runesbob-wiring")
    return wiring.bridge


@service(scope="global", interface_override=RuneBridgeService, name="runesbob-service")
def runesbob_service_factory(container: Container):
    wiring: RuneBridgeWiring = container.get(interface=RuneBridgeWiring, name="runesbob-wiring")
    return wiring.service
