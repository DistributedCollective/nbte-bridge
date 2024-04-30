import logging

from anemic.ioc import (
    auto,
    autowired,
)
from pyramid.config import Configurator
from pyramid.httpexceptions import HTTPNotFound
from pyramid.request import Request
from pyramid.view import (
    view_config,
    view_defaults,
)
from sqlalchemy.orm import Session

from bridge.api.exceptions import ApiException
from bridge.common.evm.provider import Web3

from .models import Bridge
from .service import RuneBridgeService

logger = logging.getLogger(__name__)


@view_defaults(renderer="json")
class RuneBridgeApiViews:
    request: Request
    web3: Web3 = autowired(auto)
    runesrsk_service: RuneBridgeService = autowired(RuneBridgeService, name="runesrsk-service")
    runesbob_service: RuneBridgeService = autowired(RuneBridgeService, name="runesbob-service")
    dbsession: Session = autowired(auto)

    def __init__(self, request):
        self.request = request
        self.container = request.container
        bridge_name = self.request.matchdict["bridge"]
        if bridge_name == "runes":  # support the old /api/v1/runes/ namespace
            bridge_name = "runesrsk"
        bridge = self.dbsession.query(Bridge).filter_by(name=bridge_name).first()
        if not bridge:
            raise HTTPNotFound("bridge not found")
        self.bridge_id = bridge.id
        self.bridge_name = bridge_name

    @view_config(route_name="runes_generate_deposit_address", request_method="POST")
    def generate_deposit_address(self):
        data = self.request.json_body
        evm_address = data.get("evm_address")
        if not evm_address:
            raise ApiException("Must specify evm_address")
        deposit_address = self._get_service().generate_deposit_address(
            evm_address=evm_address,
            dbsession=self.dbsession,
        )
        return {"deposit_address": deposit_address}

    @view_config(route_name="runes_get_last_scanned_bitcoin_block", request_method="GET")
    def get_last_scanned_bitcoin_block(self):
        last_scanned_block = self._get_service().get_last_scanned_bitcoin_block(self.dbsession)
        return {"last_scanned_block": last_scanned_block}

    @view_config(
        route_name="runes_get_deposits_since_block_for_evm_address",
        request_method="GET",
    )
    def get_rune_deposits_since_block_for_evm_address(self):
        # TODO: This api is kinda badly designed
        evm_address = self.request.matchdict["evm_address"]
        lastblock = self.request.matchdict["lastblock"]
        deposits = self._get_service().get_pending_deposits_for_evm_address(
            evm_address=evm_address,
            last_block=lastblock,
            dbsession=self.dbsession,
        )
        return {
            "deposits": deposits,
        }

    def _get_service(self):
        if self.bridge_name == "runesrsk":
            return self.runesrsk_service
        elif self.bridge_name == "runesbob":
            return self.runesbob_service
        else:
            raise ApiException(f"Invalid bridge name: {self.bridge_name}")


def includeme(config: Configurator):
    config.add_route("runes_generate_deposit_address", "/:bridge/deposit-addresses/")
    config.add_route("runes_get_last_scanned_bitcoin_block", "/:bridge/last-scanned-btc-block/")
    config.add_route(
        "runes_get_deposits_since_block_for_evm_address",
        "/:bridge/deposits/:evm_address/:lastblock",
    )
