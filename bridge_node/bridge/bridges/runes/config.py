from dataclasses import dataclass
from decimal import Decimal

from eth_typing import ChecksumAddress

from bridge.common.btc.types import BitcoinNetwork


@dataclass()
class RuneBridgeConfig:
    bridge_id: str
    rune_bridge_contract_address: ChecksumAddress
    evm_rpc_url: str
    btc_rpc_wallet_url: str
    ord_api_url: str
    btc_num_required_signers: int
    btc_network: BitcoinNetwork
    btc_base_derivation_path: str
    evm_block_safety_margin: int = 0
    evm_default_start_block: int = 1
    runes_to_evm_fee_percentage_decimal: Decimal = Decimal("0.4")
    btc_min_confirmations: int = 1
    btc_min_postage_sat: int = 10_000
    btc_listsinceblock_buffer: int = 6
    btc_max_fee_rate_sats_per_vbyte: int = 300


@dataclass(repr=False)
class RuneBridgeSecrets:
    evm_private_key: str
    btc_master_xpriv: str
    btc_master_xpubs: list[str]
    btc_rpc_auth: str | None = None
    ord_api_auth: str | None = None

    def __repr__(self):
        return "RuneBridgeSecrets(******)"
