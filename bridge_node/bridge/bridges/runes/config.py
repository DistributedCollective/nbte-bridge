from dataclasses import dataclass
from eth_typing import ChecksumAddress


@dataclass()
class RuneBridgeConfig:
    bridge_id: str
    rune_bridge_contract_address: ChecksumAddress
    evm_rpc_url: str
    btc_rpc_wallet_url: str
    ord_api_url: str
    btc_base_derivation_path: str = "m/13/0/0"
    evm_block_safety_margin: int = 0
    evm_default_start_block: int = 1


@dataclass(repr=False)
class RuneBridgeSecrets:
    evm_private_key: str
    btc_master_xpriv: str
    btc_master_xpubs: list[str]
    btc_rpc_auth: str | None = None
    ord_api_auth: str | None = None

    def __repr__(self):
        return "RuneBridgeSecrets(******)"
