import json
from decimal import Decimal

from .. import compose


class OrdService(compose.ComposeService):
    def __init__(self, service, request=None):
        super().__init__(service, user="ord", request=request)

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


class OrdWallet:
    def __init__(
        self,
        ord: OrdService,
        *,
        name: str = "ord",
        mnemonic: str = None,
        passphrase: str = None,
    ):
        self.ord = ord
        self.name = name
        self.mnemonic = mnemonic
        self.passphrase = passphrase

    def cli(self, *args):
        return self.ord.cli("wallet", "--name", self.name, *args)

    def create(self):
        ret = self.cli("create")
        if self.mnemonic is None:
            self.mnemonic = ret["mnemonic"]
        if self.passphrase is None:
            self.passphrase = ret["passphrase"]
        return ret

    def get_rune_balance(self, rune: str, divisibility: int):
        balances = self.cli("balance")
        balance_dec = Decimal(balances["runes"].get(rune, 0))
        return balance_dec / (10**divisibility)

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

    def generate_address(self):
        return self.cli("receive")["address"]
