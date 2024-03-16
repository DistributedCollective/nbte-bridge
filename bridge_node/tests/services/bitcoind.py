import json

from bridge.common.btc.rpc import BitcoinRPC

from .. import compose


class BitcoindService(compose.ComposeService):
    rpc_url: str
    rpc: BitcoinRPC

    def __init__(self, request):
        super().__init__("bitcoind", user="bitcoin", request=request)
        self.rpc_url = "http://polaruser:polarpass@localhost:18443"
        self.rpc = BitcoinRPC(self.rpc_url)

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
