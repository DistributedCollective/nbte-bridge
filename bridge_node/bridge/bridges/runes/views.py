import logging

from anemic.ioc import (
    auto,
    autowired,
)
from pyramid.config import Configurator
from pyramid.request import Request
from pyramid.view import (
    view_config,
    view_defaults,
)
from sqlalchemy.orm import Session

from bridge.api.exceptions import ApiException
from bridge.common.evm.provider import Web3

from .service import RuneBridgeService

logger = logging.getLogger(__name__)


@view_defaults(renderer="json")
class RuneBridgeApiViews:
    request: Request
    web3: Web3 = autowired(auto)
    service: RuneBridgeService = autowired(auto)
    dbsession: Session = autowired(auto)

    def __init__(self, request):
        self.request = request
        self.container = request.container

    @view_config(route_name="runes_generate_deposit_address", request_method="POST")
    def generate_deposit_address(self):
        data = self.request.json_body
        evm_address = data.get("evm_address")
        if not evm_address:
            raise ApiException("Must specify evm_address")
        deposit_address = self.service.generate_deposit_address(
            evm_address=evm_address,
            dbsession=self.dbsession,
        )
        return {"deposit_address": deposit_address}

    @view_config(route_name="runes_get_last_scanned_bitcoin_block", request_method="GET")
    def get_last_scanned_bitcoin_block(self):
        last_scanned_block = self.service.get_last_scanned_bitcoin_block(self.dbsession)
        return {"last_scanned_block": last_scanned_block}

    @view_config(
        route_name="runes_get_deposits_since_block_for_evm_address",
        request_method="GET",
    )
    def get_rune_deposits_since_block_for_evm_address(self):
        # TODO: This api is kinda badly designed
        evm_address = self.request.matchdict["evm_address"]
        lastblock = self.request.matchdict["lastblock"]
        deposits = self.service.get_pending_deposits_for_evm_address(
            evm_address=evm_address,
            last_block=lastblock,
            dbsession=self.dbsession,
        )
        return {
            "deposits": deposits,
        }


def includeme(config: Configurator):
    config.add_route("runes_generate_deposit_address", "/deposit-addresses/")
    config.add_route("runes_get_last_scanned_bitcoin_block", "/last-scanned-btc-block/")
    config.add_route(
        "runes_get_deposits_since_block_for_evm_address",
        "/deposits/:evm_address/:lastblock",
    )
