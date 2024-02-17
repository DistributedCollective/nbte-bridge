import logging

from anemic.ioc import auto, autowired
from pyramid.config import Configurator
from pyramid.view import view_config, view_defaults

from eth_utils import is_hex, is_hex_address
from bridge.common.evm.provider import Web3
from bridge.common.evm.account import Account
from bridge.common.evm.contracts import BridgeContract
from bridge.common.tap.deposits import TapDepositService


logger = logging.getLogger(__name__)


class ApiException(Exception):
    status_code = 400


@view_defaults(renderer="json")
class ApiViews:
    web3: Web3 = autowired(auto)
    evm_account: Account = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    tap_deposit_service: TapDepositService = autowired(auto)

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

    @view_config(route_name="generate_tap_deposit_address", request_method="POST")
    def generate_tap_deposit_address(self):
        data = self.request.json_body

        rsk_address = data.get('rsk_address')
        if not rsk_address:
            raise ApiException('Must specify rsk_address')

        if not is_hex_address(rsk_address):
            raise ApiException('rsk_address must be a hex address')

        rsk_token_address = data.get('rsk_token_address')
        if rsk_token_address is not None and not is_hex_address(rsk_token_address):
            raise ApiException('rskTokenAddress must be a hex address')

        tap_asset_id = data.get('tap_asset_id')
        if tap_asset_id is not None and not is_hex(tap_asset_id):
            raise ApiException('tap_asset_id must be a hex string')

        if not (tap_asset_id or rsk_token_address):
            raise ApiException('Must specify either tap_assed_id or rsk_token_address')
        if tap_asset_id and rsk_token_address:
            raise ApiException('Must specify only one of tap_assed_id or rsk_token_address')

        tap_amount = data.get('tap_amount')
        rsk_amount = data.get('rsk_amount')
        if rsk_amount is not None and tap_amount is not None:
            raise ApiException('Only one of tap_amount or rsk_amount must be specified')
        if not (rsk_amount or tap_amount):
            raise ApiException('Either tap_amount or rsk_amount must be specified')
        try:
            if rsk_amount is not None:
                rsk_amount = int(rsk_amount)
            if tap_amount is not None:
                tap_amount = int(tap_amount)
        except ValueError:
            raise ApiException('Amounts must be (convertible to) integers')

        address = self.tap_deposit_service.generate_deposit_address(
            tap_asset_id=tap_asset_id,
            tap_amount=tap_amount,
            user_rsk_address=rsk_address,
            rsk_token_address=rsk_token_address,
            rsk_amount=rsk_amount,
        )
        return {
            'deposit_address': address.tap_address
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
    config.add_route("generate_tap_deposit_address", "/tap/deposit-addresses/")
