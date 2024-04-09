from __future__ import annotations
from decimal import Decimal
import dataclasses


@dataclasses.dataclass
class RuneToEvmTransfer:
    evm_address: str
    amount_raw: int
    amount_decimal: Decimal
    txid: str
    vout: int
    rune_name: str


@dataclasses.dataclass
class TokenToBtcTransfer:
    receiver_address: str
    amount_wei: int
    token_address: str
    rune_name: str


@dataclasses.dataclass
class SignRuneToEvmTransferQuestion:
    transfer: RuneToEvmTransfer


@dataclasses.dataclass
class SignRuneToEvmTransferAnswer:
    signature: str
    signer: str
