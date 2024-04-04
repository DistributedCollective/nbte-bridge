from __future__ import annotations

import json
import logging
import pathlib
import random
import string
import subprocess
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal

from bridge.common.ord.client import OrdApiClient
from .bitcoind import BitcoindService
from .. import compose
from ..utils.ord_batch import create_batch_file

MIN_RUNE_LENGTH = 16  # sensible default for regtest, minimum is at least 13
MIN_RANDOMPART_LENGTH = 8  # negligible changes for collisions
TIMEOUT = 120.0
logger = logging.getLogger(__name__)


class OrdService(compose.ComposeService):
    api_client: OrdApiClient
    api_url: str

    def __init__(
        self,
        bitcoind: BitcoindService,
        request=None,
        *,
        service: str = "ord",
        ord_api_url: str = "http://localhost:3080",
    ):
        super().__init__(service, user="ord", request=request)
        self.bitcoind = bitcoind
        self.api_url = ord_api_url
        self.api_client = OrdApiClient(
            base_url=ord_api_url,
        )

    def cli(self, *args):
        ret = self.exec(
            *self.cli_args(*args),
            timeout=TIMEOUT,
        )
        return json.loads(ret.stdout)

    def cli_args(self, *args):
        return (
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

    def create_test_wallet(self, prefix: str = "") -> OrdWallet:
        # Let's just trust that there's no collision
        if prefix:
            prefix = f"{prefix}-"
        randompart = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=MIN_RANDOMPART_LENGTH)
        )
        name = f"{prefix}{randompart}"
        wallet = OrdWallet(
            ord=self,
            name=name,
        )
        wallet.create()
        return wallet

    def mine_and_sync(
        self,
        *,
        blocks: int = 1,
        poll_interval=0.05,
        timeout: float = 10.0,
    ):
        self.bitcoind.mine(blocks, sleep=0.1)
        self.sync_with_bitcoind(poll_interval=poll_interval, timeout=timeout)

    def sync_with_bitcoind(self, *, poll_interval=0.05, timeout: float = 10.0):
        """
        Make sure ord has processed all blocks from bitcoind
        """
        start = time.time()
        bitcoind_block_count = self.bitcoind.rpc.call("getblockcount")
        while time.time() - start < timeout:
            ord_block_count = self.api_client.get("/blockcount")
            if ord_block_count >= bitcoind_block_count:
                break
            logger.info(
                "Waiting for ord to sync to block %d (current: %d)",
                bitcoind_block_count,
                ord_block_count,
            )
            time.sleep(poll_interval)
        else:
            raise TimeoutError("ORD did not sync in time")


@dataclass
class EtchingInfo:
    commit: str
    reveal: str
    rune: str
    rune_destination: str
    rune_location: str
    rune_destination: str


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
        return self.ord.cli(*self.cli_args(*args))

    def cli_args(self, *args):
        return "wallet", "--name", self.name, *args

    def create(self):
        ret = self.cli("create")
        return ret

    def get_rune_balance_decimal(self, rune: str) -> Decimal:
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
            f"{amount}:{rune}",
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

        logger.info("Etching rune %s with supply %s in batch", rune, supply)

        # Etching now happens with the `ord wallet batch` command, which requires both a yaml file
        # and at least one inscription file. In addition, the command will wait until more blocks are mined,
        # so we need to do some hacky things with Popen to get it running.
        with tempfile.TemporaryDirectory(prefix="nbtebridge-tests") as tmpdir:
            inscription_file_path = pathlib.Path(tmpdir) / "inscription.txt"
            batch_file_path = pathlib.Path(tmpdir) / "batch.batch"
            with inscription_file_path.open("w") as f:
                f.write("test inscription\n")
            with batch_file_path.open("w") as f:
                create_batch_file(
                    {
                        "mode": "separate-outputs",
                        "inscriptions": [
                            {
                                "file": str("/tmp/inscription.txt"),
                            }
                        ],
                        "etching": {
                            "rune": rune,
                            "divisibility": divisibility,
                            "premine": str(supply),
                            "supply": str(supply),
                            "symbol": symbol,
                        },
                    },
                    stream=f,
                )
            self.ord.copy_to_container(inscription_file_path, "/tmp/inscription.txt")
            self.ord.copy_to_container(batch_file_path, "/tmp/batch.batch")
            logger.info("Inscription and batch files copied to ord container")

        popen_args = self.ord.cli_args(
            *self.cli_args("batch", "--fee-rate", fee_rate, "--batch", "/tmp/batch.batch")
        )
        process = self.ord.exec_popen(
            *popen_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )
        try:
            logger.debug("Waiting ord to broadcast the commitment transaction...")
            for line in process.stderr:
                # TODO: add a timeout
                # Wait for the "Waiting for rune commitment <txid> to mature" line
                logger.info("ord stderr: %s", line.rstrip())
                if "rune commitment" in line:
                    break

            # 6 blocks for the rune commitment to mature
            logger.debug("Mining 6 blocks for the commitment to mature")
            self.ord.bitcoind.mine(6)

            retval = process.wait(timeout=TIMEOUT)
            if retval != 0:
                logger.error(
                    "ord batch failed with return code %d. Stdout: %s, Stderr: %s",
                    retval,
                    process.stdout.read(),
                    process.stderr.read(),
                )
                raise compose.ComposeExecException(process.stderr.read())

            # process_output looks like this:
            # {'commit': 'e8e58c55840e6493104fa6ab43a4f986407bae6fe8861325b8cf7bc90fcc4ffe', 'commit_psbt': None,
            #  'inscriptions': [
            #      {'destination': 'bcrt1pt47jp64qeqctut7r67j7grpxnkqq6tukldqepruhn3lkvnlpkyuqyd4ec7',
            #       'id': 'acc173689c4351943725c417c574ac12cdad34c5f4088b469879cefde0741ee1i0',
            #       'location': 'acc173689c4351943725c417c574ac12cdad34c5f4088b469879cefde0741ee1:0:0'}],
            #  'parent': None,
            #  'reveal': 'acc173689c4351943725c417c574ac12cdad34c5f4088b469879cefde0741ee1', 'reveal_broadcast': True,
            #  'reveal_psbt': None,
            #  'rune': {'destination': 'bcrt1ph94h9wz4jrz4qamsu4rwz9tdc3rhrnu69vhr6q0yjh7g7kz8h8rs5n0j2w',
            #           'location': 'acc173689c4351943725c417c574ac12cdad34c5f4088b469879cefde0741ee1:1',
            #           'rune': 'RUNETESTNRHPWVFMTTQP'}
            process_output = json.load(process.stdout)
            logger.debug("ord output: %s", process_output)
        finally:
            if process.poll() is None:
                process.terminate()

        self.ord.mine_and_sync()

        return EtchingInfo(
            commit=process_output["commit"],
            reveal=process_output["reveal"],
            rune=process_output["rune"]["rune"],
            rune_destination=process_output["rune"]["destination"],
            rune_location=process_output["rune"]["location"],
        )

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

        random_part_length = max(20 - len(prefix), MIN_RANDOMPART_LENGTH)
        random_part = "".join(random.choices(string.ascii_uppercase, k=random_part_length))
        rune = f"{prefix}{random_part}"
        return self.etch_rune(rune=rune, symbol=symbol, supply=supply, divisibility=divisibility)

    def get_new_address(self) -> str:
        addr = self.cli("receive")["addresses"][0]
        self.addresses.append(addr)
        return addr

    def get_receiving_address(self) -> str:
        if self.addresses:
            return self.addresses[0]
        return self.get_new_address()

    def unlock_unspent(self):
        # XXX: there's an ord bug where it complains that output is already locked
        # after sending anything, even after a block is mined.
        # this should fix it
        self.ord.bitcoind.cli(f"-rpcwallet={self.name}", "lockunspent", "true")
