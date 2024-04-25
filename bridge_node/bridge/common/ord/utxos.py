import functools
from dataclasses import dataclass

from .client import OrdApiClient
from .types import (
    Runish,
    coerce_rune,
)


class UnindexedOutput(ValueError):
    pass


@dataclass(frozen=True)
class OrdOutput:
    txid: str
    vout: int
    amount_satoshi: int
    rune_balances: dict[str, int]
    inscriptions: list[str]

    def get_rune_balance(self, rune: Runish):
        rune = get_normalized_rune_name(rune)
        return self.rune_balances.get(rune, 0)

    def has_ord_balances(self):
        return bool(self.rune_balances or self.inscriptions)

    def has_rune_balances(self):
        return bool(self.rune_balances)


class OrdOutputCache:
    def __init__(
        self,
        *,
        ord_client: OrdApiClient,
        cache_size: int = 1024,
    ):
        self._ord_client = ord_client
        # Do not use lru_cache directly on instance methods
        self.get_ord_output = functools.lru_cache(maxsize=cache_size)(self.get_ord_output)

    def get_ord_output(self, txid: str, vout: int) -> OrdOutput:
        output_response = self._ord_client.get_output(txid=txid, vout=vout)

        # unindexed outputs don't have the rune balances visible, so we must take great care not to use them
        if not output_response["indexed"]:
            raise UnindexedOutput(output_response)

        assert output_response["transaction"] == txid

        rune_balances = {}
        for rune_name, entry in output_response["runes"]:
            normalized_name = get_normalized_rune_name(rune_name)
            assert normalized_name not in rune_balances  # not sure what to do if it is
            rune_balances[normalized_name] = entry["amount"]

        return OrdOutput(
            txid=txid,
            vout=vout,
            amount_satoshi=output_response["value"],
            rune_balances=rune_balances,
            inscriptions=output_response["inscriptions"],
        )


def get_normalized_rune_name(rune: Runish) -> str:
    """
    Remove spacers from rune name
    """
    return coerce_rune(rune).name
