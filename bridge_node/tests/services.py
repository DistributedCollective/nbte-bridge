import dotenv

from decimal import Decimal
import json

from . import compose

assert compose.ENV_FILE.exists(), f"Missing {compose.ENV_FILE}"

config = dotenv.dotenv_values(compose.ENV_FILE)
POSTGRES_PASSWORD = config["POSTGRES_PASSWORD"]


class PostgresService(compose.ComposeService):
    dsn_from_docker: str
    dsn_outside_docker: str

    def __init__(self, request):
        super().__init__("postgres", request=request)
        self.dsn_from_docker = f"postgresql://postgres:{POSTGRES_PASSWORD}@localhost:5432/"
        self.dsn_outside_docker = f"postgresql://postgres:{POSTGRES_PASSWORD}@localhost:65432/"

    def cli(self, *args, dsn: str = None):
        return self.exec(
            "psql",
            "-d",
            dsn or self.dsn_from_docker,
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
    rpc_url: str

    def __init__(self, request):
        super().__init__("hardhat", request=request)
        self.rpc_url = "http://localhost:18545"

    def run_json_command(self, *args):
        return json.loads(self.exec("npx", "hardhat", "--network", "localhost", *args).stdout)


class BitcoindService(compose.ComposeService):
    rpc_url: str

    def __init__(self, request):
        super().__init__("bitcoind", user="bitcoin", request=request)
        self.rpc_url = "http://polaruser:polarpass@localhost:18443"

    def cli(self, *args):
        # Most commands are parseable to json, but some aren't. Example: getnewaddress
        return self.exec(
            "bitcoin-cli",
            "-chain=regtest",
            "-rpcuser=polaruser",
            "-rpcpassword=polarpass",
            *args,
        ).stdout

    def get_wallet_rpc_url(self, wallet_name):
        return f"{self.rpc_url}/wallet/{wallet_name}"

    def mine(self, blocks=1, address=None):
        if address is None:
            address = "bcrt1qtxysk2megp39dnpw9va32huk5fesrlvutl0zdpc29asar4hfkrlqs2kzv5"
        return json.loads(self.cli("generatetoaddress", blocks, address))
