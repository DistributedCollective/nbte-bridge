from __future__ import annotations
from decimal import Decimal
import dataclasses


@dataclasses.dataclass
class RuneToEvmTransfer:
    evm_address: str
    amount_raw: int
    amount_decimal: Decimal
    net_amount_raw: int
    txid: str
    vout: int
    rune_name: str
    rune_number: int


@dataclasses.dataclass
class RuneTokenToBtcTransfer:
    receiver_address: str
    net_rune_amount: int
    token_address: str
    rune_name: str


@dataclasses.dataclass
class SignRuneToEvmTransferQuestion:
    transfer: RuneToEvmTransfer


@dataclasses.dataclass
class SignRuneToEvmTransferAnswer:
    signature: str
    signer: str
    message_hash: str


@dataclasses.dataclass
class SignRuneTokenToBtcTransferQuestion:
    transfer: RuneTokenToBtcTransfer
    unsigned_psbt_serialized: str


@dataclasses.dataclass
class SignRuneTokenToBtcTransferAnswer:
    signed_psbt_serialized: str
    signer_xpub: str
