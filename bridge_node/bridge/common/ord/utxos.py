import functools
from dataclasses import dataclass
from .client import OrdApiClient


@dataclass(frozen=True)
class OrdOutput:
    txid: str
    vout: int
    amount_satoshi: int
    rune_balances: dict[str, int]
    inscriptions: list[str]

    def get_rune_balance(self, rune: str):
        rune = normalize_rune(rune)
        return self.rune_balances.get(rune, 0)

    def has_ord_balances(self):
        return bool(self.rune_balances or self.inscriptions)


class OrdOutputCache:
    def __init__(
        self,
        *,
        ord_client: OrdApiClient,
        cache_size: int = 1024,
    ):
        self._ord_client = ord_client
        # Do not use lru_cache directly on instane methods
        self.get_ord_output = functools.lru_cache(maxsize=cache_size)(self.get_ord_output)

    def get_ord_output(self, txid: str, vout: int) -> OrdOutput:
        output_response = self._ord_client.get_output(txid=txid, vout=vout)
        assert output_response["transaction"] == txid
        rune_balances = {}
        for rune_name, entry in output_response["runes"]:
            assert rune_name not in rune_balances  # not sure what to do if it is
            rune_balances[normalize_rune(rune_name)] = entry["amount"]
        return OrdOutput(
            txid=txid,
            vout=vout,
            amount_satoshi=output_response["value"],
            rune_balances=rune_balances,
            inscriptions=output_response["inscriptions"],
        )


def normalize_rune(rune: str) -> str:
    """
    Remove spacers from rune name
    """
    ret = "".join(c for c in rune if c not in (".", "•"))
    assert ret.isalpha()
    assert ret.isupper()
    return ret
