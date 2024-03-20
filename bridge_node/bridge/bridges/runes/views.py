import logging

from anemic.ioc import auto, autowired
from pyramid.config import Configurator
from pyramid.request import Request
from pyramid.view import view_config, view_defaults

from bridge.common.evm.provider import Web3
from bridge.api.exceptions import ApiException
from .service import RuneBridgeService

logger = logging.getLogger(__name__)


@view_defaults(renderer="json")
class RuneBridgeApiViews:
    request: Request
    web3: Web3 = autowired(auto)
    service: RuneBridgeService = autowired(auto)

    def __init__(self, request):
        self.request = request
        self.container = request.container

    @view_config(route_name="runes_generate_deposit_address", request_method="POST")
    def generate_deposit_address(self):
        data = self.request.json_body
        evm_address = data.get("evm_address")
        if not evm_address:
            raise ApiException("Must specify evm_address")
        deposit_address = self.service.generate_deposit_address(evm_address=evm_address)
        return {"deposit_address": deposit_address}


def includeme(config: Configurator):
    config.add_route("runes_generate_deposit_address", "/deposit-addresses/")
