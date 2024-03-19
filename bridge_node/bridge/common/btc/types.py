import binascii
import dataclasses
from decimal import Decimal
from typing import Any, Optional

from bitcointx.core import COutPoint

from .utils import from_satoshi, to_satoshi


@dataclasses.dataclass(frozen=True)
class UTXO:
    txid: str
    vout: int
    amount_satoshi: int
    confirmations: int
    address: Optional[str] = None
    # raw: dict[str, Any] = dataclasses.field(repr=False, default_factory=dict)

    @classmethod
    def from_rpc_response(cls, rpc_dict: dict[str, Any]):
        r = cls(
            txid=rpc_dict["txid"],
            vout=rpc_dict["vout"],
            amount_satoshi=to_satoshi(rpc_dict["amount"]),
            confirmations=rpc_dict["confirmations"],
            address=rpc_dict.get("address"),
            # raw=rpc_dict,
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
