import logging

from anemic.ioc import auto, autowired
from eth_utils import is_checksum_address
from pyramid.config import Configurator
from pyramid.view import view_config, view_defaults

from ..btc.deposits import BitcoinDepositService
from ..evm.provider import Web3
from ..evm.account import Account
from ..evm.contracts import BridgeContract

logger = logging.getLogger(__name__)


class ApiException(Exception):
    status_code = 400


@view_defaults(renderer="json")
class ApiViews:
    btc_deposit_service: BitcoinDepositService = autowired(auto)
    web3: Web3 = autowired(auto)
    evm_account: Account = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)

    def __init__(self, request):
        self.request = request
        self.container = request.container

    @view_config(route_name="stats", request_method="GET")
    def stats(self):
        # TODO: cache this to avoid spam
        if not self.web3.is_connected():
            healthy = False
            reason = "No connection to EVM node"
        elif not self.web3.eth.get_code(self.bridge_contract.address):
            healthy = False
            reason = "Bridge contract not deployed"
        elif not self.bridge_contract.functions.isFederator(self.evm_account.address).call():
            healthy = False
            reason = "Not a federator"
        else:
            healthy = True
            reason = None
        logger.info("Is healthy: %s, reason: %s", healthy, reason)
        return {
            "is_healthy": healthy,
            "reason": reason,
        }

    @view_config(route_name="generate_deposit_address", request_method="POST")
    def generate_deposit_address(self):
        evm_address = self.request.json_body["evm_address"]
        if not is_checksum_address(evm_address):
            raise ApiException(
                f"Invalid evm_address: {evm_address}. "
                "Address must be a checksummed 0x-prefixed EVM address"
            )
        deposit_info = self.btc_deposit_service.generate_deposit_address(evm_address, index=0)
        return {
            "deposit_address": deposit_info.btc_deposit_address,
        }

    @view_config(context=ApiException)
    def api_exception_view(self, exc: ApiException):
        self.request.response.status_code = exc.status_code
        return {
            "error": str(exc),
        }

    @view_config(context=Exception)
    def uncaught_exception_view(self, exc: Exception):
        self.request.response.status_code = 500
        logger.exception("Error in API view", exc_info=exc)
        return {
            "error": "An unknown error occured",
        }


@view_config(route_name="index", renderer="json")
def index(request):
    return {
        "hello": "world",
    }


def includeme(config: Configurator):
    config.add_route("stats", "/stats/")
    config.add_route("generate_deposit_address", "/deposit-addresses/")
