import json
from typing import cast

from eth_utils import to_hex
from web3 import Web3
from web3.types import RPCEndpoint

from bridge.common.evm.utils import create_web3
from .. import compose


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
        return self.exec("npx", "hardhat", "--network", "localhost", *args).stdout

    def run_json_command(self, *args):
        return json.loads(self.cli(*args))

    def make_request(self, method: str, *args):
        return self.web3.provider.make_request(cast(RPCEndpoint, method), args)

    def mine(self, blocks: int = 1):
        return self.make_request("hardhat_mine", [to_hex(blocks)])
