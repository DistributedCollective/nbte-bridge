from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from eth_account import Account
from .bridge import RuneBridge
from .service import RuneBridgeService
from .config import RuneBridgeConfig, RuneBridgeSecrets
from .evm import load_rune_bridge_abi
from ...common.p2p.network import Network
from ...common.services.transactions import TransactionManager
from ...common.btc.rpc import BitcoinRPC
from ...common.evm.utils import create_web3
from ...common.ord.simple_wallet import SimpleOrdWallet
from ...common.ord.client import OrdApiClient


@dataclass
class RuneBridgeWiring:
    bridge: RuneBridge
    service: RuneBridgeService


def wire_rune_bridge(
    *,
    config: RuneBridgeConfig,
    secrets: RuneBridgeSecrets,
    network: Network,
    transaction_manager: TransactionManager,
) -> RuneBridgeWiring:
    bitcoin_rpc = BitcoinRPC(
        url=_add_auth(config.btc_rpc_wallet_url, secrets.btc_rpc_auth),
    )
    ord_client = OrdApiClient(
        base_url=_add_auth(config.ord_api_url, secrets.ord_api_auth),
    )
    ord_wallet = SimpleOrdWallet(
        ord_client=ord_client,
        bitcoin_rpc=bitcoin_rpc,
    )

    evm_account = Account.from_key(secrets.evm_private_key)
    web3 = create_web3(config.evm_rpc_url, account=evm_account)
    rune_bridge_contract = web3.eth.contract(
        address=config.rune_bridge_contract_address,
        abi=load_rune_bridge_abi("RuneBridge"),
    )

    service = RuneBridgeService(
        config=config,
        transaction_manager=transaction_manager,
        bitcoin_rpc=bitcoin_rpc,
        ord_client=ord_client,
        ord_wallet=ord_wallet,
        web3=web3,
        rune_bridge_contract=rune_bridge_contract,
    )

    bridge = RuneBridge(
        bridge_id=config.bridge_id,
        network=network,
        service=service,
    )

    return RuneBridgeWiring(bridge=bridge, service=service)


def _add_auth(url: str, auth: str | None) -> str:
    if not auth:
        return url
    parts = urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc:
        # replacing existing auth
        netloc = netloc.split("@", 1)[1]
    netloc = f"{auth}@{netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
