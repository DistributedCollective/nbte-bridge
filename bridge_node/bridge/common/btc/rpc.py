import decimal
import json
import time
import typing
import urllib.parse
from decimal import Decimal

import requests
from anemic.ioc import Container, service

from bridge.config import Config


class JSONRPCError(requests.HTTPError):
    def __init__(self, *, message, code=None, request=None, response=None, jsonrpc_data=None):
        self.code = code
        self.message = message
        super().__init__(
            {
                "message": message,
                "code": code,
                "jsonrpc_data": jsonrpc_data,
            },
            request=request,
            response=response,
        )


class BitcoinRPC:
    """Requests-based RPC client, because bitcointx.rpc.RPCCaller is riddled with cryptic http errors"""

    def __init__(self, url: str):
        self._id_count = 0
        urlparts = urllib.parse.urlparse(url)
        self._auth = (urlparts.username, urlparts.password) if (urlparts.username or urlparts.password) else None
        if urlparts.port:
            netloc = f"{urlparts.hostname}:{urlparts.port}"
        else:
            netloc = urlparts.hostname
        self._url = urllib.parse.urlunparse(
            urllib.parse.ParseResult(
                scheme=urlparts.scheme,
                netloc=netloc,
                path=urlparts.path,
                params=urlparts.params,
                query=urlparts.query,
                fragment=urlparts.fragment,
            )
        )

    # Interface to any service call
    def call(self, service_name: str, *args: typing.Any):
        return self._jsonrpc_call(service_name, args)

    # __getattr__ for allowing syntactic sugar to any service call
    def __getattr__(self, name: str):
        if name.startswith("_"):
            # No internals
            raise AttributeError(name)

        def caller(*args: typing.Any):
            return self.call(name, *args)

        caller.__name__ = name
        return caller

    # Type-annotate all calls implemented with __getattr__, implement methods ourselves

    def _jsonrpc_call(self, method, params):
        self._id_count += 1

        jsonrpc_data = {
            "jsonrpc": "2.0",
            "id": self._id_count,
            "method": method,
            "params": params,
        }
        postdata = json.dumps(
            jsonrpc_data,
            cls=DecimalJSONEncoder,
        )
        response = requests.post(
            self._url,
            data=postdata,
            auth=self._auth,
            headers={
                "Content-Type": "application/json",
            },
        )

        # Don't raise here, we want sane error messages
        # try:
        #     response.raise_for_status()
        # except requests.HTTPError as e:
        #     raise JSONRPCError(
        #         message=str(e),
        #         response=response,
        #         jsonrpc_data=jsonrpc_data,
        #     ) from e

        try:
            response_json = json.loads(
                response.text,
                parse_float=Decimal,
            )
        except json.JSONDecodeError as e:
            raise JSONRPCError(
                message=str(e),
                response=response,
                jsonrpc_data=jsonrpc_data,
            ) from e
        error = response_json.get("error")
        if error is not None or not response.ok:
            if isinstance(error, dict):
                raise JSONRPCError(
                    message=error["message"],
                    code=error["code"],
                    response=response,
                    jsonrpc_data=jsonrpc_data,
                )
            raise JSONRPCError(
                message=str(error),
                response=response,
                jsonrpc_data=jsonrpc_data,
            )
        if "result" not in response_json:
            raise JSONRPCError(
                message="No result in response",
                response=response,
                jsonrpc_data=jsonrpc_data,
            )
        return response_json["result"]

    def mine_blocks(self, num: int = 1, to_address: str = None, *, sleep: float = 1.1) -> list[str]:
        # Regtest only: mine blocks
        if to_address is None:
            # Use a random address if none is provided (not important)
            to_address = "bcrt1qtxysk2megp39dnpw9va32huk5fesrlvutl0zdpc29asar4hfkrlqs2kzv5"
        ret = self.call("generatetoaddress", num, to_address)
        if sleep:
            # Sleep here by default, otherwise the tap nodes will not have time to process the block(s)
            time.sleep(sleep)
        return ret


class DecimalJSONEncoder(json.JSONEncoder):
    # Forked from bitcointx/rpc.py... seems like f'{somedecimal:.08f}' no longer works for python3.11?
    def default(self, o: typing.Any) -> typing.Any:
        if isinstance(o, decimal.Decimal):
            r = float(o)
            if f"{r:.08f}" != f"{o:.8f}":
                raise TypeError(
                    f"value {o!r} lost precision beyond acceptable range "
                    f"when converted to float: {r:.08f} != {o:.8f}"
                )
            return r
        return super().default(o)


@service(interface_override=BitcoinRPC, scope="global")
def bitcoin_rpc_factory(container: Container):
    config = container.get(interface=Config)

    return BitcoinRPC(config.btc_rpc_url)
