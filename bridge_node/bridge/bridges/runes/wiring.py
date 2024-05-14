from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from eth_account import Account

from ...common.btc.rpc import BitcoinRPC
from ...common.evm.utils import create_web3
from ...common.messengers import Messenger
from ...common.ord.client import OrdApiClient
from ...common.ord.multisig import OrdMultisig
from ...common.p2p.network import Network
from ...common.services.transactions import TransactionManager
from .bridge import RuneBridge
from .config import RuneBridgeConfig, RuneBridgeSecrets
from .evm import load_rune_bridge_abi
from .service import RuneBridgeService


@dataclass
class RuneBridgeWiring:
    bridge: RuneBridge
    service: RuneBridgeService
    multisig: OrdMultisig


def wire_rune_bridge(
    *,
    config: RuneBridgeConfig,
    secrets: RuneBridgeSecrets,
    network: Network,
    transaction_manager: TransactionManager,
    messenger: Messenger | None = None,
) -> RuneBridgeWiring:
    bitcoin_rpc = BitcoinRPC(
        url=_add_auth(config.btc_rpc_wallet_url, secrets.btc_rpc_auth),
    )
    ord_client = OrdApiClient(
        base_url=_add_auth(config.ord_api_url, secrets.ord_api_auth),
    )

    ord_multisig = OrdMultisig(
        master_xpriv=secrets.btc_master_xpriv,
        master_xpubs=secrets.btc_master_xpubs,
        num_required_signers=config.btc_num_required_signers,
        base_derivation_path=config.btc_base_derivation_path,
        bitcoin_rpc=bitcoin_rpc,
        ord_client=ord_client,
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
        ord_multisig=ord_multisig,
        web3=web3,
        rune_bridge_contract=rune_bridge_contract,
        evm_account=evm_account,
        messenger=messenger,
    )

    bridge = RuneBridge(
        bridge_id=config.bridge_id,
        network=network,
        service=service,
    )

    return RuneBridgeWiring(bridge=bridge, service=service, multisig=ord_multisig)


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
