import logging
from decimal import Decimal

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
    IncomingBtcTx,
    Rune,
    RuneDeposit,
    RuneTokenDeposit,
    User,
)
from ...bridges.runes.service import RuneBridgeService
from ..exceptions import ApiException

logger = logging.getLogger(__name__)


class MonitorViews:
    request: Request
    dbsession: Session = autowired(auto)
    runesrsk_service: RuneBridgeService = autowired(RuneBridgeService, name="runesrsk-service")
    runesbob_service: RuneBridgeService = autowired(RuneBridgeService, name="runesbob-service")

    def __init__(self, request):
        self.request = request
        self.container = request.container
        bridge_name = self.request.matchdict["bridge"]
        bridge = self.dbsession.query(Bridge).filter_by(name=bridge_name).first()
        if not bridge:
            raise HTTPNotFound("bridge not found")
        self.bridge_id = bridge.id
        self.bridge_name = bridge_name

    @view_config(
        route_name="monitor_deposits",
        request_method="GET",
        renderer="templates/monitor/deposits.jinja2",
    )
    def deposits(self):
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
        incoming_btc_txs = (
            self.dbsession.query(IncomingBtcTx)
            .filter_by(
                bridge_id=self.bridge_id,
            )
            .order_by(
                IncomingBtcTx.created_at.desc(),
            )
            .limit(100)
        )

        return {
            "rune_deposits": rune_deposits,
            "rune_token_deposits": rune_token_deposits,
            "incoming_btc_txs": incoming_btc_txs,
        }

    @view_config(
        route_name="monitor_runes",
        request_method="GET",
        renderer="templates/monitor/runes.jinja2",
    )
    def runes(self):
        runes = (
            self.dbsession.query(Rune)
            .filter_by(
                bridge_id=self.bridge_id,
            )
            .order_by(
                Rune.id.desc(),
            )
            .limit(100)
        )

        return {
            "runes": runes,
        }

    @view_config(
        route_name="monitor_users",
        request_method="GET",
        renderer="templates/monitor/users.jinja2",
    )
    def users(self):
        users = (
            self.dbsession.query(User)
            .filter_by(
                bridge_id=self.bridge_id,
            )
            .order_by(
                User.id.desc(),
            )
            .all()
        )
        return {
            "users": users,
        }

    @view_config(
        route_name="monitor_multisig",
        request_method="GET",
        renderer="templates/monitor/multisig.jinja2",
    )
    def multisig(self):
        service = self._get_runebridge_service()
        ord_client = service.ord_client
        multisig = service.ord_multisig
        utxos_with_ord_outputs = multisig.list_utxos_with_ord_outputs()
        rune_balances = dict()
        runic_balance_sat = 0
        cardinal_balance_sat = 0
        unindexed_balance_sat = 0
        for utxo, ord_output in utxos_with_ord_outputs:
            if not ord_output:
                unindexed_balance_sat += utxo.amount_satoshi
                continue
            if ord_output.has_rune_balances():
                for rune_name, amount in ord_output.rune_balances.items():
                    if rune_name not in rune_balances:
                        rune_balances[rune_name] = 0
                    rune_balances[rune_name] += amount

                runic_balance_sat += utxo.amount_satoshi
            else:
                cardinal_balance_sat += utxo.amount_satoshi

        rune_entries = {}
        for rune in rune_balances.keys():
            rune_response = ord_client.get_rune(rune)
            rune_entries[rune] = rune_response["entry"]

        def format_raw_rune_amount(rune: str, amount_raw: int) -> Decimal:
            return Decimal(amount_raw) / 10 ** rune_entries[rune]["divisibility"]

        return {
            "change_address": multisig.change_address,
            "utxos_with_ord_outputs": utxos_with_ord_outputs,
            "rune_balances": rune_balances,
            "runic_balance_btc": Decimal(runic_balance_sat) / 10**8,
            "cardinal_balance_btc": Decimal(cardinal_balance_sat) / 10**8,
            "unindexed_balance_btc": Decimal(unindexed_balance_sat) / 10**8,
            "rune_entries": rune_entries,
            "format_raw_rune_amount": format_raw_rune_amount,
        }

    @view_config(
        route_name="monitor_sanity_check",
        request_method="GET",
        renderer="templates/monitor/sanitycheck.jinja2",
    )
    def sanity_check(self):
        # TODO: some duplication in here
        service = self._get_runebridge_service()
        multisig = service.ord_multisig
        utxos_with_ord_outputs = multisig.list_utxos_with_ord_outputs()
        rune_balances = dict()
        for _, ord_output in utxos_with_ord_outputs:
            if not ord_output:
                continue
            for rune_name, amount in ord_output.rune_balances.items():
                if rune_name not in rune_balances:
                    rune_balances[rune_name] = 0
                rune_balances[rune_name] += amount

        entries = []
        for rune_name, balance_raw in rune_balances.keys():
            rune = (
                self.dbsession.query(
                    Rune,
                )
                .filter_by(
                    bridge_id=self.bridge_id,
                    name=rune_name,
                )
                .one()
            )
            balance_decimal = Decimal(balance_raw) / 10**rune.divisibility
            token_contract = service.get_rune_token(rune.n)
            if token_contract.address != "0x0000000000000000000000000000000000000000":
                decimals = token_contract.functions.decimals().call()
                supply = Decimal(token_contract.functions.totalSupply().call()) / 10**decimals
                difference = balance_decimal - supply
                difference_pct = difference / balance_decimal * 100
                token = {
                    "address": token_contract.address,
                    "name": token_contract.functions.name().call(),
                    "symbol": token_contract.functions.symbol().call(),
                }
            else:
                token = None
                difference = None
                difference_pct = None
            entries.append(
                {
                    "rune": rune.spaced_name,
                    "multisig_rune_balance": balance_decimal,
                    "token": token,
                    "difference": difference,
                    "difference_pct": difference_pct,
                }
            )

        return {
            "entries": entries,
        }

    def _get_runebridge_service(self) -> RuneBridgeService:
        if self.bridge_name == "runesrsk":
            return self.runesrsk_service
        elif self.bridge_name == "runesbob":
            return self.runesbob_service
        else:
            raise ApiException(f"Invalid bridge name: {self.bridge_name}")


def includeme(config: Configurator):
    config.add_jinja2_search_path("/srv/bridge_backend/templates")
    config.add_route("monitor_deposits", "/:bridge/deposits")
    config.add_route("monitor_runes", "/:bridge/runes")
    config.add_route("monitor_users", "/:bridge/users")
    config.add_route("monitor_multisig", "/:bridge/multisig")
    config.add_route("monitor_sanity_check", "/:bridge/sanity-check")
