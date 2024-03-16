from __future__ import annotations

import dataclasses
import random
import string
import json
from decimal import Decimal

from bridge.common.ord.client import OrdApiClient

from .. import compose


MIN_RANDOMPART_LENGTH = 8


class OrdService(compose.ComposeService):
    api_client: OrdApiClient

    def __init__(self, service, *, request=None, ord_api_url: str = None):
        super().__init__(service, user="ord", request=request)
        self.api_client = OrdApiClient(
            base_url=ord_api_url,
        )

    def cli(self, *args):
        ret = self.exec(
            "ord",
            "--chain",
            "regtest",
            "--bitcoin-rpc-url",
            "bitcoind:18443",
            "--bitcoin-rpc-username",
            "polaruser",
            "--bitcoin-rpc-password",
            "polarpass",
            "--data-dir",
            "/home/ord/data",
            *args,
        )
        return json.loads(ret.stdout)

    def create_test_wallet(self, prefix: str) -> OrdWallet:
        # Let's just trust that there's no collision
        randompart = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=MIN_RANDOMPART_LENGTH)
        )
        name = f"{prefix}-{randompart}"
        wallet = OrdWallet(
            ord=self,
            name=name,
        )
        wallet.create()
        return wallet


@dataclasses.dataclass
class EtchingInfo:
    rune: str
    transaction: str


class OrdWallet:
    def __init__(
        self,
        ord: OrdService,
        *,
        name: str = "ord",
    ):
        self.ord = ord
        self.name = name
        self.addresses = []

    def cli(self, *args):
        return self.ord.cli("wallet", "--name", self.name, *args)

    def create(self):
        ret = self.cli("create")
        return ret

    def get_rune_balance(self, rune: str) -> Decimal:
        rune_response = self.ord.api_client.get_rune(rune)
        if not rune_response:
            raise ValueError(f"Rune {rune} not found")
        balances = self.cli("balance")
        balance_dec = Decimal(balances["runes"].get(rune, 0))
        return balance_dec / (10 ** rune_response["entry"]["divisibility"])

    def get_balance_btc(self) -> Decimal:
        balances = self.cli("balance")
        # TODO: cardinal or total? or we could also get this from bitcoin rpc
        # but maybe cardinal is good because we don't want to use balances locked for runes
        balance_dec = Decimal(balances["cardinal"])
        return balance_dec / Decimal("1e8")

    def send_runes(
        self,
        *,
        rune: str,
        receiver: str,
        amount: int | Decimal,
        fee_rate: int | Decimal = 1,
    ):
        ret = self.cli(
            "send",
            "--fee-rate",
            fee_rate,
            receiver,
            f"{amount} {rune}",
        )
        return ret

    def etch_rune(
        self,
        *,
        rune: str,
        symbol: str,
        supply: int | Decimal,
        divisibility: int,
        fee_rate: int = 1,
    ) -> EtchingInfo:
        if not rune.isalpha() or not rune.isupper():
            raise ValueError("rune must be an uppercase alphabetic string")
        ret = self.cli(
            "etch",
            "--divisibility",
            divisibility,
            "--fee-rate",
            fee_rate,
            "--rune",
            rune,
            "--supply",
            supply,
            "--symbol",
            symbol,
        )
        return EtchingInfo(transaction=ret["transaction"], rune=ret["rune"])

    def etch_test_rune(
        self,
        prefix: str,
        *,
        supply: int | Decimal = 100_000_000,
        divisibility: int = 18,
        symbol: str = None,
    ) -> EtchingInfo:
        if not symbol:
            symbol = prefix[0]

        random_part_length = min(20 - len(prefix), MIN_RANDOMPART_LENGTH)
        random_part = "".join(random.choices(string.ascii_uppercase, k=random_part_length))
        rune = f"{prefix}{random_part}"
        return self.etch_rune(rune=rune, symbol=symbol, supply=supply, divisibility=divisibility)

    def get_new_address(self) -> str:
        addr = self.cli("receive")["address"]
        self.addresses.append(addr)
        return addr

    def get_receiving_address(self) -> str:
        if self.addresses:
            return self.addresses[0]
        return self.get_new_address()
