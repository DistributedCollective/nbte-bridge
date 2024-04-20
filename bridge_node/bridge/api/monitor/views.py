import logging

from anemic.ioc import (
    auto,
    autowired,
)
from pyramid.config import Configurator
from pyramid.httpexceptions import HTTPNotFound
from pyramid.request import Request
from pyramid.view import view_config
from sqlalchemy.orm import Session

from ...bridges.runes.models import (
    Bridge,
    RuneDeposit,
    RuneTokenDeposit,
    IncomingBtcTx,
)

logger = logging.getLogger(__name__)


class MonitorViews:
    request: Request
    dbsession: Session = autowired(auto)

    def __init__(self, request):
        self.request = request
        self.container = request.container
        bridge_name = self.request.matchdict["bridge"]
        bridge = self.dbsession.query(Bridge).filter_by(name=bridge_name).first()
        if not bridge:
            raise HTTPNotFound("bridge not found")
        self.bridge_id = bridge.id

    @view_config(
        route_name="monitor_deposits",
        request_method="GET",
        renderer="templates/monitor.jinja2",
    )
    def monitor(self):
        incoming_btc_txs = (
            self.dbsession.query(IncomingBtcTx)
            .filter_by(
                bridge_id=self.bridge_id,
            )
            .order_by(
                RuneDeposit.created_at.desc(),
            )
            .limit(100)
        )
        rune_deposits = (
            self.dbsession.query(RuneDeposit)
            .filter_by(
                bridge_id=self.bridge_id,
            )
            .order_by(
                RuneDeposit.created_at.desc(),
            )
            .limit(100)
        )
        rune_token_deposits = (
            self.dbsession.query(RuneTokenDeposit)
            .filter_by(
                bridge_id=self.bridge_id,
            )
            .order_by(
                RuneTokenDeposit.created_at.desc(),
            )
            .limit(100)
        )

        return {
            "rune_deposits": rune_deposits,
            "rune_token_deposits": rune_token_deposits,
            "incoming_btc_txs": incoming_btc_txs,
        }


def includeme(config: Configurator):
    config.add_jinja2_search_path("/srv/bridge_backend/templates")
    config.add_route("monitor_deposits", "/deposits/:bridge")
