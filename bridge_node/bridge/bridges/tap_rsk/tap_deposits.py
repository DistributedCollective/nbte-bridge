import dataclasses
import logging

from anemic.ioc import Container, auto, autowired, service
from eth_utils import add_0x_prefix, remove_0x_prefix, to_checksum_address
from sqlalchemy.orm.session import Session
from web3.constants import ADDRESS_ZERO

from bridge.common.services.key_value_store import KeyValueStore
from bridge.common.tap.client import TapRestClient

from .models import (
    TapDepositAddress,
    TapToRskTransfer,
)
from .rsk import BridgeContract

logger = logging.getLogger(__name__)


# TODO: have this in a model too
@dataclasses.dataclass
class BridgeableAsset:
    """
    struct BridgeableAsset {
        TestToken rskToken;
        bytes32 tapAssetId;
        uint256 tapAmountDivisor;
        bool tapNative;
        string tapAssetName;
    }
    """

    rsk_token: str
    tap_asset_id: str
    tap_amount_divisor: int
    tap_native: bool
    tap_asset_name: str


@service(scope="transaction")
class TapDepositService:
    tap_client: TapRestClient = autowired(auto)
    key_value_store: KeyValueStore = autowired(auto)
    dbsession: Session = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)

    def __init__(self, container: Container):
        self.container = container

    def generate_deposit_address(
        self,
        *,
        user_rsk_address: str,
        tap_amount: int = None,
        tap_asset_id: str = None,
        rsk_amount: int = None,
        rsk_token_address: str = None,
    ) -> TapDepositAddress:
        if tap_amount is None and rsk_amount is None:
            raise ValueError("Either tap_amount or rsk_amount must be specified")
        if tap_amount is not None and rsk_amount is not None:
            raise ValueError("Only one of tap_amount or rsk_amount must be specified")
        if tap_asset_id is None and rsk_token_address is None:
            raise ValueError("Either tap_asset_id or rsk_token_address must be specified")
        if tap_asset_id is not None and rsk_token_address is not None:
            raise ValueError("Only one of tap_asset_id or rsk_token_address must be specified")
        if tap_asset_id is not None and tap_asset_id.startswith("0x"):
            tap_asset_id = remove_0x_prefix(tap_asset_id)

        if rsk_token_address is not None:
            asset = self._get_bridgeable_asset(rsk_token=rsk_token_address)
        else:
            asset = self._get_bridgeable_asset(tap_asset_id=tap_asset_id)

        divisor = asset.tap_amount_divisor
        if rsk_amount is not None:
            if rsk_amount % divisor != 0:
                raise ValueError(f"rsk_amount must be divisible by {divisor}")
            tap_amount = rsk_amount // divisor
        elif tap_amount is not None:
            rsk_amount = tap_amount * divisor

        user_rsk_address = to_checksum_address(user_rsk_address)
        tap_address_response = self.tap_client.create_address(
            asset_id=asset.tap_asset_id,
            amount=tap_amount,
        )

        ret = TapDepositAddress(
            rsk_address=user_rsk_address,
            tap_address=tap_address_response.address,
            rsk_token_address=asset.rsk_token,
            tap_asset_id=asset.tap_asset_id,
            tap_amount=tap_amount,
            rsk_amount=rsk_amount,
        )
        self.dbsession.add(ret)
        return ret

    def get_deposit_addresses(self) -> list[TapDepositAddress]:
        return self.dbsession.query(TapDepositAddress).all()

    def _get_bridgeable_asset(self, *, rsk_token: str = None, tap_asset_id: str = None):
        if rsk_token and tap_asset_id:
            raise ValueError("Only one of rsk_token_address or tap_asset_id must be specified")
        if rsk_token:
            rsk_token = to_checksum_address(rsk_token)
            asset = self.bridge_contract.functions.assetsByRskTokenAddress(rsk_token).call()
        else:
            asset = self.bridge_contract.functions.assetsByTaprootAssetId(add_0x_prefix(tap_asset_id)).call()

        rsk_token, tap_asset_id, tap_amount_divisor, tap_native, tap_asset_name = asset
        if rsk_token == ADDRESS_ZERO:
            raise ValueError("Asset not found")
        if isinstance(tap_asset_id, bytes):
            tap_asset_id = tap_asset_id.hex()
        tap_asset_id = remove_0x_prefix(tap_asset_id)
        return BridgeableAsset(
            rsk_token=rsk_token,
            tap_asset_id=tap_asset_id,
            tap_amount_divisor=tap_amount_divisor,
            tap_native=tap_native,
            tap_asset_name=tap_asset_name,
        )

    def scan_new_deposits(self):
        # TODO: this should to be improved so that we don't have to scan everything every time
        # maybe use this: https://lightning.engineering/api-docs/api/taproot-assets/taproot-assets/subscribe-receive-asset-event-ntfns/index.html
        previous_deposits = self.dbsession.query(
            TapToRskTransfer.deposit_btc_tx_id, TapToRskTransfer.deposit_btc_tx_vout
        ).all()
        previous_outpoints = set(
            (deposit_btc_tx_id, deposit_btc_tx_vout) for deposit_btc_tx_id, deposit_btc_tx_vout in previous_deposits
        )

        deposit_addresses = self.get_deposit_addresses()
        logger.info(
            "Processing deposits (%s addresses, %s seen deposits)...",
            len(deposit_addresses),
            len(previous_outpoints),
        )
        for deposit_address in deposit_addresses:
            tap_address = deposit_address.tap_address
            logger.info("Checking %s...", tap_address)
            result = self.tap_client.list_receives(
                address=tap_address,
                status="ADDR_EVENT_STATUS_COMPLETED",
            )
            events = result["events"]
            for event in events:
                outpoint_raw = event["outpoint"]
                btc_tx_id, btc_tx_vout = outpoint_raw.split(":")
                btc_tx_vout = int(btc_tx_vout)
                outpoint = (btc_tx_id, btc_tx_vout)

                if outpoint in previous_outpoints:
                    logger.info("Already processed %s", outpoint)
                    continue

                if event["addr"]["encoded"] != tap_address:
                    raise ValueError("Address mismatch: {} != {}".format(event["addr"]["encoded"], tap_address))
                status = event["status"]
                if status == "ADDR_EVENT_STATUS_COMPLETED":
                    logger.info("Found %s: %s", outpoint, status)
                    previous_outpoints.add(outpoint)
                    deposit = TapToRskTransfer(
                        deposit_address=deposit_address,
                        deposit_btc_tx_id=btc_tx_id,
                        deposit_btc_tx_vout=btc_tx_vout,
                    )
                    self.dbsession.add(deposit)
                    self.dbsession.flush()
                else:
                    # Just raise error because list_receives filter should work
                    raise ValueError(f"Outpoint {outpoint} not yet completed, status: {status}")
                    # logger.info("Outpoint %s not yet completed, status: %s", outpoint, status)

        logger.info("Done scanning deposits.")
