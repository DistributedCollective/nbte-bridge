from __future__ import annotations

import random
import string
import json
from decimal import Decimal
import time
import logging
import tempfile
import threading

from bridge.common.ord.client import OrdApiClient
from .bitcoind import BitcoindService

from .. import compose
import pathlib
from ..utils.ord_batch import create_batch_file

MIN_RUNE_LENGTH = 16  # sensible default for regtest, minimum is at least 13
MIN_RANDOMPART_LENGTH = 8  # negligible changes for collisions
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
            timeout=60,
        )
        return ret.stdout

    def cli_json(self, *args):
        return json.loads(self.cli(*args))

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

    def cli_json(self, *args):
        return json.loads(self.cli(*args))

    def create(self):
        ret = self.cli_json("create")
        return ret

    def get_rune_balance_decimal(self, rune: str) -> Decimal:
        rune_response = self.ord.api_client.get_rune(rune)
        if not rune_response:
            raise ValueError(f"Rune {rune} not found")
        balances = self.cli_json("balance")
        balance_dec = Decimal(balances["runes"].get(rune, 0))
        return balance_dec / (10 ** rune_response["entry"]["divisibility"])

    def get_balance_btc(self) -> Decimal:
        balances = self.cli_json("balance")
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
        ret = self.cli_json(
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
    ) -> str:
        if not rune.isalpha() or not rune.isupper():
            raise ValueError("rune must be an uppercase alphabetic string")

        logger.info("Etching rune %s with supply %s in batch", rune, supply)

        # Etching now happens with the `ord wallet batch` command, which requires both a yaml file
        # and at least one inscription file. In addition, the command will wait until more blocks are mined,
        # so we have to do some threading magic to mine blocks in the background.
        # TODO: check if we could instead CTRL-C the process, then mine, then `ord wallet resume`
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

            batch_processed = False

            def mine_bitcoins():
                logger.info("Starting bitcoin mining")
                time.sleep(2)
                while not batch_processed:
                    logger.info("Mining 6 blocks")
                    # 6 blocks for it to mature, one more block to see rewards
                    self.ord.bitcoind.mine(6)
                    time.sleep(1)
                logger.info("Stopping bitcoin mining")

            t = threading.Thread(target=mine_bitcoins)
            t.start()
            try:
                logger.info("Launching batch command")
                self.cli("batch", "--fee-rate", fee_rate, "--batch", "/tmp/batch.batch")
                logger.info("Batch command done")
            finally:
                batch_processed = True
                t.join()

            self.ord.mine_and_sync()
        return rune

    def etch_test_rune(
        self,
        prefix: str,
        *,
        supply: int | Decimal = 100_000_000,
        divisibility: int = 18,
        symbol: str = None,
    ) -> str:
        if not symbol:
            symbol = prefix[0]

        random_part_length = max(20 - len(prefix), MIN_RANDOMPART_LENGTH)
        random_part = "".join(random.choices(string.ascii_uppercase, k=random_part_length))
        rune = f"{prefix}{random_part}"
        return self.etch_rune(rune=rune, symbol=symbol, supply=supply, divisibility=divisibility)

    def get_new_address(self) -> str:
        addr = self.cli_json("receive")["addresses"][0]
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
