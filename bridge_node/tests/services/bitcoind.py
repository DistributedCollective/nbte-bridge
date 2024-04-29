from __future__ import annotations

import logging
import random
import string
import time
from decimal import Decimal
from typing import Protocol

from bridge.common.btc.rpc import BitcoinRPC, JSONRPCError

from .. import compose

logger = logging.getLogger(__name__)


MIN_RANDOMPART_LENGTH = 8


class FundableWallet(Protocol):
    name: str

    def get_balance_btc(self) -> Decimal: ...

    def get_receiving_address(self) -> str: ...


class BitcoindService(compose.ComposeService):
    rpc_url: str
    rpc: BitcoinRPC
    # Root wallet is used to fund other wallets in a sane fashion
    root_wallet: BitcoinWallet

    def __init__(self, request=None):
        super().__init__("bitcoind", user="bitcoin", request=request)

        self.rpc_url = "http://polaruser:polarpass@localhost:18443"
        self.rpc = BitcoinRPC(self.rpc_url)
        self._root_wallet = None

    @property
    def root_wallet(self) -> BitcoinWallet:
        if self._root_wallet is None:
            self._root_wallet, _ = self.load_or_create_wallet("root")

        return self._root_wallet

    def cli(self, *args):
        # Most commands are parseable to json, but some aren't. Example: getnewaddress
        return self.exec(
            "bitcoin-cli",
            "-chain=regtest",
            "-rpcuser=polaruser",
            "-rpcpassword=polarpass",
            *args,
        )[0]

    def mine(self, blocks=1, address=None, *, sleep: float = 0.25):
        ret = self.root_wallet.mine(blocks, address)
        time.sleep(sleep)
        return ret

    def create_test_wallet(
        self,
        prefix: str = "",
        *,
        fund: bool = False,
        blank: bool = False,
        disable_private_keys: bool = False,
    ) -> BitcoinWallet:
        """
        Creates a randomly-named wallet, suitable for testing
        """
        if prefix:
            prefix = f"{prefix}-"

        while True:
            randompart = "".join(random.choices(string.ascii_lowercase + string.digits, k=MIN_RANDOMPART_LENGTH))
            wallet_name = f"{prefix}{randompart}"
            wallet, created = self.load_or_create_wallet(
                wallet_name,
                blank=blank,
                disable_private_keys=disable_private_keys,
            )

            if created:
                break

            logger.info("Duplicate wallet name: %s. Trying again.")

        if fund:
            self.fund_wallets(wallet)

        return wallet

    def fund_wallets(
        self,
        *wallets: FundableWallet,
        amount_to_send: Decimal = Decimal(1),
    ):
        """
        Fund wallets, but instead of mining to them, use the root wallet to send btc to them

        This should offer non-trivial test speedups especially if containers are kept after each test
        """
        self._mine_initial_blocks()

        # Ensure root wallet is funded
        self._ensure_root_wallet_balance(amount_to_send * len(wallets))

        for wallet in wallets:
            address = wallet.get_receiving_address()
            self.root_wallet.send(amount_btc=amount_to_send, receiver=address)
            logger.info("Funded wallet %s with %s BTC", wallet.name, amount_to_send)

        self.mine(1)

    def fund_addresses(self, *addresses: str, amount_to_send: Decimal = Decimal(1)):
        assert amount_to_send >= Decimal("0.01"), "Sending too little, transactions might fail"

        self._mine_initial_blocks()
        self._ensure_root_wallet_balance(amount_to_send * len(addresses))

        for address in addresses:
            logger.info("Funding address %s with %s BTC", address, amount_to_send)
            self.root_wallet.send(amount_btc=amount_to_send, receiver=address)

        self.mine(1)

    def get_wallet_rpc_url(self, wallet_name: str) -> str:
        return f"{self.rpc_url}/wallet/{wallet_name}"

    def get_wallet_rpc(self, wallet_name: str) -> BitcoinRPC:
        return BitcoinRPC(self.get_wallet_rpc_url(wallet_name))

    def load_or_create_wallet(
        self, wallet_name: str, *, blank: bool = False, disable_private_keys: bool = False
    ) -> tuple[BitcoinWallet, bool]:
        wallet = self.load_wallet(wallet_name)
        if wallet:
            return wallet, False

        self.rpc.call(
            "createwallet",
            wallet_name,
            disable_private_keys,
            blank,
        )

        logger.info("Created wallet %s", wallet_name)
        wallet = BitcoinWallet(
            name=wallet_name,
            rpc=self.get_wallet_rpc(wallet_name),
        )

        return wallet, True

    def load_wallet(self, wallet_name) -> BitcoinWallet | None:
        wallets = self.rpc.call("listwallets")

        if wallet_name in wallets:
            logger.info("Using already loaded wallet %s", wallet_name)
        else:
            try:
                self.rpc.call("loadwallet", wallet_name)
                logger.info("Loaded wallet %s", wallet_name)
            except JSONRPCError:
                return None

        return BitcoinWallet(name=wallet_name, rpc=BitcoinRPC(self.get_wallet_rpc_url(wallet_name)))

    def _mine_initial_blocks(self):
        blockcount = self.rpc.call("getblockcount")
        if blockcount <= 100:
            logger.info("Mining initial blocks to see some coins")
            self.root_wallet.mine(101)

    def _ensure_root_wallet_balance(self, balance: Decimal):
        while self.root_wallet.get_balance_btc() < balance:
            logger.info("Mining to the root wallet to have enough balance for funding")
            self.root_wallet.mine(10)


class BitcoinWallet:
    name: str
    rpc: BitcoinRPC
    addresses: list[str]

    def __init__(self, *, name: str, rpc: BitcoinRPC):
        self.name = name
        self.rpc = rpc
        self.addresses = []

    def get_new_address(self) -> str:
        address = self.rpc.call("getnewaddress")
        self.addresses.append(address)
        return address

    def get_receiving_address(self) -> str:
        if self.addresses:
            return self.addresses[0]
        return self.get_new_address()

    def mine(self, blocks=1, address=None):
        if address is None:
            address = self.get_receiving_address()
        return self.rpc.call("generatetoaddress", blocks, address)

    def get_balance_btc(self) -> Decimal:
        return self.rpc.call("getbalance")

    def send(self, *, amount_btc: Decimal | int, receiver: str):
        return self.rpc.call("sendtoaddress", receiver, amount_btc)

    def import_address(self, address: str):
        self.rpc.call("importaddress", address)
        self.addresses.append(address)
