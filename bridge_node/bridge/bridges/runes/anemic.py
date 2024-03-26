# This file is here because certain places (MainBridge, views...)
# want to have RuneBridge and RuneBridgeService in the IoC container
# Maybe we should just have manual wiring everywhere?
from anemic.ioc import (
    Container,
    service,
)

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
from ...common.p2p.network import Network
from ...common.services.transactions import TransactionManager
from ...config import Config


@service(scope="global", interface_override=RuneBridgeWiring)
def rune_bridge_wiring_factory(container: Container):
    config: Config = container.get(interface=Config)
    return wire_rune_bridge(
        config=RuneBridgeConfig(
            bridge_id="runesrsk",
            rune_bridge_contract_address=config.runes_rune_bridge_contract_address,
            evm_rpc_url=config.runes_evm_rpc_url,
            btc_rpc_wallet_url=config.runes_btc_rpc_wallet_url,
            ord_api_url=config.runes_ord_api_url,
            btc_base_derivation_path=config.runes_btc_base_derivation_path,
            evm_block_safety_margin=config.evm_block_safety_margin,
            evm_default_start_block=config.runes_evm_default_start_block,
        ),
        secrets=RuneBridgeSecrets(
            evm_private_key=config.secret_runes_evm_private_key,
            btc_master_xpriv=config.secret_runes_btc_master_xpriv,
            btc_master_xpubs=config.secret_runes_btc_master_xpubs,
            btc_rpc_auth=config.secret_runes_btc_rpc_auth,
            ord_api_auth=config.secret_runes_ord_api_auth,
        ),
        network=container.get(interface=Network),
        transaction_manager=container.get(interface=TransactionManager),
    )


@service(scope="global", interface_override=RuneBridge)
def rune_bridge_factory(container: Container):
    wiring: RuneBridgeWiring = container.get(interface=RuneBridgeWiring)
    return wiring.bridge


@service(scope="global", interface_override=RuneBridgeService)
def rune_bridge_service_factory(container: Container):
    wiring: RuneBridgeWiring = container.get(interface=RuneBridgeWiring)
    return wiring.service
