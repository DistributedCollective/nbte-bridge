import json
from decimal import Decimal
import typing
import urllib.parse
import requests

from anemic.ioc import Container, service
import bitcointx
import bitcointx.rpc

from ..config import Config


class JSONRPCError(requests.HTTPError):
    def __init__(self, *, message, code=None, request=None, response=None):
        self.code = code
        self.message = message
        super().__init__(
            {
                "message": message,
                "code": code,
            },
            request=request,
            response=response,
        )


class BitcoinRPC:
    """Requests-based RPC client, because bitcointx.rpc.RPCCaller is riddled with cryptic http errors"""

    def __init__(self, url: str):
        self._id_count = 0
        urlparts = urllib.parse.urlparse(url)
        self._auth = (
            (urlparts.username, urlparts.password)
            if (urlparts.username or urlparts.password)
            else None
        )
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

        postdata = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._id_count,
                "method": method,
                "params": params,
            },
            cls=bitcointx.rpc.DecimalJSONEncoder,
        )
        response = requests.post(
            self._url,
            data=postdata,
            auth=self._auth,
            headers={
                "Content-Type": "application/json",
            },
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise JSONRPCError(
                message=str(e),
                response=response,
            ) from e

        try:
            response_json = json.loads(
                response.text,
                parse_float=Decimal,
            )
        except json.JSONDecodeError as e:
            raise JSONRPCError(
                message=str(e),
                response=response,
            ) from e
        error = response_json.get("error")
        if error is not None:
            if isinstance(error, dict):
                raise JSONRPCError(
                    message=error["message"],
                    code=error["code"],
                    response=response,
                )
            raise JSONRPCError(
                message=str(error),
                response=response,
            )
        if "result" not in response_json:
            raise JSONRPCError(
                message="No result in response",
                response=response,
            )
        return response_json["result"]


@service(interface_override=BitcoinRPC, scope="global")
def bitcoin_rpc_factory(container: Container):
    config = container.get(interface=Config)

    return BitcoinRPC(config.btc_rpc_url)
