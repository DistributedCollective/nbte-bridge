import dataclasses
import logging

from anemic.ioc import Container, service, autowired, auto

from sqlalchemy.orm.session import Session

from eth_utils import remove_0x_prefix, to_checksum_address, add_0x_prefix
from web3.constants import ADDRESS_ZERO
from ..common.key_value_store import KeyValueStore
from .client import TapRestClient
from ..evm.contracts import BridgeContract

logger = logging.getLogger(__name__)


# TODO: use a real DB model for deposit addresses and deposits instead of keyvaluestore
@dataclasses.dataclass
class DepositAddress:
    CURRENT_VERSION = 1
    version: int
    user_rsk_address: str
    tap_address: str
    tap_asset_id: str
    rsk_token_address: str
    tap_amount: int
    rsk_amount: int


@dataclasses.dataclass
class TapDeposit:
    receiver_rsk_address: str
    deposit_tap_address: str
    btc_tx_id: str
    btc_tx_vout: int


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
        rsk_token_address: str = None
    ) -> DepositAddress:
        if tap_amount is None and rsk_amount is None:
            raise ValueError("Either tap_amount or rsk_amount must be specified")
        if tap_amount is not None and rsk_amount is not None:
            raise ValueError("Only one of tap_amount or rsk_amount must be specified")
        if tap_asset_id is None and rsk_token_address is None:
            raise ValueError("Either tap_asset_id or rsk_token_address must be specified")
        if tap_asset_id is not None and rsk_token_address is not None:
            raise ValueError("Only one of tap_asset_id or rsk_token_address must be specified")
        if tap_asset_id is not None and tap_asset_id.startswith('0x'):
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

        ret = DepositAddress(
            version=DepositAddress.CURRENT_VERSION,
            user_rsk_address=user_rsk_address,
            tap_address=tap_address_response.address,
            rsk_token_address=asset.rsk_token,
            tap_asset_id=asset.tap_asset_id,
            tap_amount=tap_amount,
            rsk_amount=rsk_amount,
        )

        # TODO: use a real model instead of keyvaluestore
        deposit_addresses = self.key_value_store.get_value('tap:deposit_addresses', [])
        deposit_addresses.append(dataclasses.asdict(ret))
        self.key_value_store.set_value('tap:deposit_addresses', deposit_addresses)
        return ret

    def get_deposit_addresses(self) -> list[DepositAddress]:
        deposit_addresses_raw = self.key_value_store.get_value('tap:deposit_addresses', [])
        return [
            DepositAddress(**d)
            for d in deposit_addresses_raw
        ]

    def _get_bridgeable_asset(self, *, rsk_token: str = None, tap_asset_id: str = None):
        if rsk_token and tap_asset_id:
            raise ValueError("Only one of rsk_token_address or tap_asset_id must be specified")
        if rsk_token:
            rsk_token = to_checksum_address(rsk_token)
            asset = self.bridge_contract.functions.assetsByRskTokenAddress(rsk_token).call()
        else:
            asset = self.bridge_contract.functions.assetsByTaprootAssetId(
                add_0x_prefix(tap_asset_id)
            ).call()

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

    def scan_new_deposits(self) -> list[TapDeposit]:
        # TODO: better datamodel for this
        processed_event_outpoints = set(self.key_value_store.get_value('tap:processed_event_outpoints', []))

        deposit_addresses = self.get_deposit_addresses()
        ret: list[TapDeposit] = []
        logger.info(
            "Processing deposits (%s addresses, %s processed deposits)...",
            len(deposit_addresses),
            len(processed_event_outpoints),
        )
        for deposit_address in deposit_addresses:
            if deposit_address.version != DepositAddress.CURRENT_VERSION:
                # Could migrate DepositAddress here. But maybe we want to use SQLAlchemy anyway
                logger.error(
                    "Invalid version (expected %s): %s",
                    DepositAddress.CURRENT_VERSION,
                    deposit_address,
                )
                continue
            tap_address = deposit_address.tap_address
            logger.info("Checking %s...", tap_address)
            result = self.tap_client.list_receives(address=tap_address)
            events = result['events']
            for event in events:
                outpoint = event['outpoint']
                if outpoint in processed_event_outpoints:
                    logger.info("Already processed %s", outpoint)
                    continue
                processed_event_outpoints.add(outpoint)

                if event['addr']['encoded'] != tap_address:
                    raise ValueError("Address mismatch: {} != {}".format(event['addr']['encoded'], tap_address))
                status = event['status']
                logger.info("Found %s: %s", outpoint, status)
                btc_tx_id, btc_tx_vout = outpoint.split(':')
                btc_tx_vout = int(btc_tx_vout)
                if status == 'ADDR_EVENT_STATUS_COMPLETED':
                    ret.append(
                        TapDeposit(
                            receiver_rsk_address=deposit_address.user_rsk_address,
                            deposit_tap_address=tap_address,
                            btc_tx_id=btc_tx_id,
                            btc_tx_vout=btc_tx_vout,
                        )
                    )

        self.key_value_store.set_value('tap:processed_event_outpoints', list(processed_event_outpoints))
        logger.info("Done scanning deposits.")
        return ret