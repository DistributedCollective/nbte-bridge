from typing import Literal
import binascii
import dataclasses
from decimal import Decimal
from typing import Any, Optional

from bitcointx.core import COutPoint
from bitcointx.core.script import CScript

from .utils import from_satoshi, to_satoshi


BitcoinNetwork = Literal["mainnet", "testnet", "signet", "regtest"]
BITCOIN_NETWORKS = ["mainnet", "testnet", "signet", "regtest"]


def is_bitcoin_network(network: str) -> bool:
    return network in BITCOIN_NETWORKS


@dataclasses.dataclass(frozen=True)
class UTXO:
    txid: str
    vout: int
    amount_satoshi: int
    confirmations: int
    spendable: bool
    solvable: bool
    safe: bool
    desc: Optional[str] = None  # only if solvable
    address: Optional[str] = None
    witness_script: Optional[CScript] = None
    # raw: dict[str, Any] = dataclasses.field(repr=False, default_factory=dict)

    @classmethod
    def from_rpc_response(cls, rpc_dict: dict[str, Any]):
        r = cls(
            txid=rpc_dict["txid"],
            vout=rpc_dict["vout"],
            amount_satoshi=to_satoshi(rpc_dict["amount"]),
            confirmations=rpc_dict["confirmations"],
            solvable=rpc_dict["solvable"],
            spendable=rpc_dict["spendable"],
            safe=rpc_dict["safe"],
            desc=rpc_dict.get("desc"),
            address=rpc_dict.get("address"),
            witness_script=(
                CScript.fromhex(rpc_dict["witnessScript"]) if "witnessScript" in rpc_dict else None
            ),
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
