import logging

from anemic.ioc import auto, autowired
from eth_utils import is_hex, is_hex_address
from pyramid.config import Configurator
from pyramid.request import Request
from pyramid.view import view_config, view_defaults

from bridge.bridges.tap_rsk.models import RskToTapTransferBatchStatus, TapToRskTransferBatchStatus
from bridge.bridges.tap_rsk.rsk_to_tap import RskToTapService
from bridge.bridges.tap_rsk.tap_to_rsk import TapToRskService
from bridge.common.evm.provider import Web3

from ..bridges.tap_rsk.rsk import BridgeContract
from ..bridges.tap_rsk.tap_deposits import TapDepositService
from ..common.evm.account import Account
from ..config import Config
from .exceptions import ApiException

logger = logging.getLogger(__name__)


# TODO: factor out tap-bridge specific views


@view_defaults(renderer="json")
class ApiViews:
    request: Request
    config: Config
    web3: Web3 = autowired(auto)
    evm_account: Account = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    tap_deposit_service: TapDepositService = autowired(auto)
    tap_to_rsk_service: TapToRskService = autowired(auto)
    rsk_to_tap_service: RskToTapService = autowired(auto)

    def __init__(self, request):
        self.request = request
        self.container = request.container

    def is_bridge_enabled(self, bridge_name: str):
        return "all" in self.config.enabled_bridges or bridge_name in self.config.enabled_bridges

    @view_config(route_name="stats", request_method="GET")
    def stats(self):
        # TODO: cache this to avoid spam
        healthy = True
        reason = None
        if not self.web3.is_connected():
            healthy = False
            reason = "No connection to EVM node"

        # TODO: work this api better
        if healthy:
            if self.is_bridge_enabled("taprsk"):
                if not self.web3.eth.get_code(self.bridge_contract.address):
                    healthy = False
                    reason = "Tap Bridge contract not deployed"
                elif not self.bridge_contract.functions.isFederator(self.evm_account.address).call():
                    healthy = False
                    reason = "Not a federator (tap bridge)"

        logger.info("Is healthy: %s, reason: %s", healthy, reason)
        return {
            "is_healthy": healthy,
            "reason": reason,
        }

    @view_config(route_name="tap_to_rsk_transfers", request_method="POST")
    def tap_to_rsk_transfers(self):
        if not self.is_bridge_enabled("taprsk"):
            raise ApiException("Tap to RSK bridge is not enabled")
        data = self.request.json_body
        address = data.get("address")

        transfers = self.tap_to_rsk_service.get_transfers_by_address(address)

        return {
            "transfers": [
                {
                    "id": transfer.db_id,
                    "address": transfer.tap_address,
                    "status": TapToRskTransferBatchStatus.status_to_str(transfer.status),
                }
                for transfer in transfers
            ]
        }

    @view_config(route_name="rsk_to_tap_transfers", request_method="POST")
    def rsk_to_tap_transfers(self):
        if not self.is_bridge_enabled("taprsk"):
            raise ApiException("Tap to RSK bridge is not enabled")
        data = self.request.json_body
        address = data.get("address")

        transfers = self.rsk_to_tap_service.get_transfers_by_address(address)

        return {
            "transfers": [
                {
                    "id": transfer.db_id,
                    "address": transfer.sender_rsk_address,
                    "status": RskToTapTransferBatchStatus.status_to_str(transfer.status),
                }
                for transfer in transfers
            ]
        }

    @view_config(route_name="generate_tap_deposit_address", request_method="POST")
    def generate_tap_deposit_address(self):
        if not self.is_bridge_enabled("taprsk"):
            raise ApiException("Tap to RSK bridge is not enabled")

        data = self.request.json_body

        rsk_address = data.get("rsk_address")
        if not rsk_address:
            raise ApiException("Must specify rsk_address")

        if not is_hex_address(rsk_address):
            raise ApiException("rsk_address must be a hex address")

        rsk_token_address = data.get("rsk_token_address")
        if rsk_token_address is not None and not is_hex_address(rsk_token_address):
            raise ApiException("rskTokenAddress must be a hex address")

        tap_asset_id = data.get("tap_asset_id")
        if tap_asset_id is not None and not is_hex(tap_asset_id):
            raise ApiException("tap_asset_id must be a hex string")

        if not (tap_asset_id or rsk_token_address):
            raise ApiException("Must specify either tap_assed_id or rsk_token_address")
        if tap_asset_id and rsk_token_address:
            raise ApiException("Must specify only one of tap_assed_id or rsk_token_address")

        tap_amount = data.get("tap_amount")
        rsk_amount = data.get("rsk_amount")
        if rsk_amount is not None and tap_amount is not None:
            raise ApiException("Only one of tap_amount or rsk_amount must be specified")
        if not (rsk_amount or tap_amount):
            raise ApiException("Either tap_amount or rsk_amount must be specified")
        try:
            if rsk_amount is not None:
                rsk_amount = int(rsk_amount)
            if tap_amount is not None:
                tap_amount = int(tap_amount)
        except ValueError as e:
            raise ApiException("Amounts must be (convertible to) integers") from e

        address = self.tap_deposit_service.generate_deposit_address(
            tap_asset_id=tap_asset_id,
            tap_amount=tap_amount,
            user_rsk_address=rsk_address,
            rsk_token_address=rsk_token_address,
            rsk_amount=rsk_amount,
        )
        return {"deposit_address": address.tap_address}

    @view_config(context=ApiException)
    def api_exception_view(self, exc: ApiException):
        self.request.response.status_code = exc.status_code
        return {
            "error": str(exc),
        }

    @view_config(context=Exception)
    def uncaught_exception_view(self, exc: Exception = None):
        self.request.response.status_code = 500
        if exc is None:
            exc = self.request.exception
        logger.exception("Error in API view", exc_info=exc)
        return {
            "error": "An unknown error occured",
        }

    # TODO: this would be useful, but it exposes internal details
    # @view_config(route_name="network_info", request_method="GET")
    # def network_info(self):
    #     return self.tap_to_rsk_service.network.get_network_info()


@view_config(route_name="index", renderer="json")
def index(request):
    return {
        "hello": "world",
    }


@view_config(route_name="error_trigger", renderer="json")
def error_trigger(request):
    1 / 0  # noqa
    return {
        "error": "grigger",
    }


# TODO: do nested config better and separate tapbridge specific views


def includeme(config: Configurator):
    config.add_route("error_trigger", "/error-trigger/")
    config.add_route("stats", "/stats/")

    config.add_route("generate_tap_deposit_address", "/tap/deposit-addresses/")
    config.add_route("tap_to_rsk_transfers", "/tap/transfers/")
    config.add_route("rsk_to_tap_transfers", "/rsk/transfers/")
    # config.add_route("network_info", "/network/")

    from ..bridges.runes import views as rune_bridge_views
    from .monitor import views as monitor_views

    config.include("pyramid_jinja2")
    config.include(rune_bridge_views)
    config.include(monitor_views, route_prefix="/monitor")
