import binascii
import dataclasses
from decimal import Decimal
from typing import Any, Optional

from bitcointx.core import COutPoint
from bitcointx.wallet import CCoinAddress
from bitcointx.core.psbt import PartiallySignedBitcoinTransaction as BitcoinTxPSBT

from .utils import from_satoshi, to_satoshi


class Transfer:
    recipient_address: str
    amount_satoshi: int

    def __init__(self, *, recipient_address: str, amount_satoshi: int):
        self.recipient_address = recipient_address
        self.amount_satoshi = amount_satoshi
        self._parsed_address = None

    def __repr__(self):
        btc = from_satoshi(self.amount_satoshi)
        return f"Transfer({btc} BTC to {self.recipient_address})"

    @property
    def parsed_address(self):
        if self._parsed_address is None:
            self._parsed_address = CCoinAddress(self.recipient_address)
        return self._parsed_address

    @property
    def recipient_script_pubkey(self):
        return self.parsed_address.to_scriptPubKey()

    def assert_valid(self):
        # TODO: add libbitcoinconsensus validation!
        if not isinstance(self.amount_satoshi, int) or self.amount_satoshi <= 0:
            raise ValueError("amount_satoshi must be a positive non-zero integer")
        if self.parsed_address is None:
            raise ValueError("recipient_address is not a valid address")
        if not self.recipient_script_pubkey.is_valid():
            raise ValueError("recipient_address deos not have a valid scriptPubKey")


@dataclasses.dataclass(frozen=True)
class UTXO:
    txid: str
    vout: int
    amount_satoshi: int
    confirmations: int
    address: Optional[str] = None
    raw: dict[str, Any] = dataclasses.field(repr=False, default_factory=dict)

    @classmethod
    def from_rpc_response(cls, rpc_dict: dict[str, Any]):
        r = cls(
            txid=rpc_dict["txid"],
            vout=rpc_dict["vout"],
            amount_satoshi=to_satoshi(rpc_dict["amount"]),
            confirmations=rpc_dict["confirmations"],
            address=rpc_dict.get("address"),
            raw=rpc_dict,
        )
        assert r.amount_btc == Decimal(rpc_dict["amount"])
        return r

    @property
    def tx_hash(self) -> bytes:
        return binascii.unhexlify(self.txid)[::-1]

    @property
    def outpoint(self) -> COutPoint:
        return COutPoint(self.tx_hash, self.vout)

    @property
    def amount_btc(self) -> Decimal:
        return from_satoshi(self.amount_satoshi)


# TODO: custom PSBT class
PSBT = BitcoinTxPSBT
