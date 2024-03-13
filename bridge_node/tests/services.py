import dotenv

from decimal import Decimal
import json

from . import compose

assert compose.ENV_FILE.exists(), f"Missing {compose.ENV_FILE}"

config = dotenv.dotenv_values(compose.ENV_FILE)
POSTGRES_PASSWORD = config["POSTGRES_PASSWORD"]


class PostgresService(compose.ComposeService):
    def __init__(self, request):
        super().__init__("postgres", request=request)
        self.local_connection_string = f"postgresql://postgres:{POSTGRES_PASSWORD}@localhost:5432/"

    def cli(self, *args, connection_string=None):
        return self.exec(
            "psql",
            "-d",
            connection_string or self.local_connection_string,
            "-c",
            " ".join(args),
        )


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


class HardhatService(compose.ComposeService):
    def __init__(self, request):
        super().__init__("hardhat", request=request)

    def run_json_command(self, *args):
        return json.loads(self.exec("npx", "hardhat", "--network", "localhost", *args).stdout)


class BitcoindService(compose.ComposeService):
    def __init__(self, request):
        super().__init__("bitcoind", request=request)
