import json

from .. import compose


class HardhatService(compose.ComposeService):
    rpc_url: str

    def __init__(self, request):
        super().__init__("hardhat", request=request)
        self.rpc_url = "http://localhost:18545"

    def cli(self, *args) -> str:
        return self.exec("npx", "hardhat", "--network", "localhost", *args).stdout

    def run_json_command(self, *args):
        return json.loads(self.cli(*args))
