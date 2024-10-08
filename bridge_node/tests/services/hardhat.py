from __future__ import annotations

import dataclasses
import json
import logging
import typing
from typing import cast

from eth_account import Account
from eth_account.account import LocalAccount
from eth_typing import ChecksumAddress
from eth_utils import to_hex
from web3 import Web3
from web3.types import RPCEndpoint

from bridge.common.evm.utils import create_web3

from .. import compose

logger = logging.getLogger(__name__)


class HardhatService(compose.ComposeService):
    rpc_url: str
    web3: Web3

    def __init__(self, request):
        super().__init__(
            "hardhat",
            build=True,  # we need to rebuild as the contracts are compiled inside the image
            request=request,
        )
        self.rpc_url = "http://localhost:18545"
        self.web3 = create_web3(self.rpc_url)

    def cli(self, *args) -> str:
        return self.exec("npx", "hardhat", "--network", "localhost", *args)

    def run_json_command(self, *args):
        output = self.cli(*args)[0]
        return json.loads(output)

    def make_request(self, method: str, args: list[typing.Any]):
        ret = self.web3.provider.make_request(cast(RPCEndpoint, method), args)
        if ret.get("error"):
            raise ValueError(ret["error"])
        return ret["result"]

    def mine(self, blocks: int = 1):
        return self.make_request("hardhat_mine", [to_hex(blocks)])

    def snapshot(self):
        return self.make_request("evm_snapshot", [])

    def revert(self, snapshot_id: str, *, check: bool = True) -> bool:
        result = self.make_request("evm_revert", [snapshot_id])
        if check and not result:
            raise ValueError("Failed to revert")
        return result

    def set_automine(self, enabled):
        return self.make_request("evm_setAutomine", [enabled])

    def create_test_wallet(
        self,
        name=None,
        *,
        fund: bool = True,
        impersonate: bool = True,
    ) -> EVMWallet:
        logger.info("Creating test evm wallet %s", name or "")
        account = Account.create()
        logger.info("Account: %s", account.address)

        if impersonate:
            logger.info("Impersonating account %s", account.address)
            self.make_request("hardhat_impersonateAccount", [account.address])

        if fund:
            amount_eth = 10.0
            logger.info("Funding %s with %s ETH", account.address, amount_eth)
            self.make_request(
                "hardhat_setBalance",
                [account.address, to_hex(Web3.to_wei(amount_eth, "ether"))],
            )

        return EVMWallet(
            name=name,
            account=account,
        )


@dataclasses.dataclass
class EVMWallet:
    account: LocalAccount
    name: str | None = None

    @property
    def address(self) -> ChecksumAddress:
        return self.account.address
