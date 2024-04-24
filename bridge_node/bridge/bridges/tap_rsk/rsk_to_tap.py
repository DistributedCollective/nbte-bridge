import logging

from anemic.ioc import Container, auto, autowired, service
from sqlalchemy.orm.session import Session

from ...common.services.transactions import TransactionManager
from ...common.tap.client import TapRestClient
from .models import (
    RskToTapTransfer,
    RskToTapTransferBatch,
    RskToTapTransferBatchStatus,
)
from .rsk import BridgeContract

logger = logging.getLogger(__name__)


SIGN_RSK_TO_TAP_QUESTION = "taprsk-sign-evm-to-tap"


@service(scope="global")
class RskToTapService:
    transaction_manager: TransactionManager = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    tap_client: TapRestClient = autowired(auto)
    batch_limit: int = 10

    def __init__(self, container: Container):
        self.container = container

    def init(self):
        # self.network.answer_with(SIGN_RSK_TO_TAP_QUESTION, self._answer_sign_rsk_to_tap)
        pass

    def process_current_transfer_batch(self):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            current_batch = self._get_or_create_current_batch(dbsession)
            if not current_batch:
                logger.info("No current RSK to TAP batch")
                return
            logger.info("Current RSK to TAP batch: %s", current_batch)
            batch_id, status = current_batch.id, current_batch.status

        if status == RskToTapTransferBatchStatus.CREATED:
            # TODO: VPSBT creation, validate balances, etc
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                batch = dbsession.query(RskToTapTransferBatch).get(batch_id)
                assert batch.status == status
                batch.status = status = RskToTapTransferBatchStatus.SENDING_TO_TAP
                recipients = [t.recipient_tap_address for t in batch.transfers]

            # TODO: sanity check, can be removed
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                batch = dbsession.query(RskToTapTransferBatch).filter_by(id=batch_id).one()
                assert batch.status == status == RskToTapTransferBatchStatus.SENDING_TO_TAP

            logger.info("Broadcasting transaction to tap")
            send_result = self.tap_client.send_assets(*recipients)
            logger.info("Transaction broadcasted to tap: %s", send_result)

            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                batch = dbsession.query(RskToTapTransferBatch).get(batch_id)
                assert batch.status == status
                batch.status = status = RskToTapTransferBatchStatus.SENT_TO_TAP
                batch.sending_result = send_result

        if status == RskToTapTransferBatchStatus.SENDING_TO_TAP:
            raise RuntimeError(f"Batch {batch_id} left in SENDING_TO_TAP state, cannot safely proceed further")

        # TODO: check mined, store info, etc
        if status == RskToTapTransferBatchStatus.SENT_TO_TAP:
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                batch = dbsession.query(RskToTapTransferBatch).get(batch_id)
                assert batch.status == status
                batch.status = status = RskToTapTransferBatchStatus.FINALIZED
            logger.info("RSK to TAP batch %s finalized", batch_id)

    def _get_or_create_current_batch(self, dbsession: Session) -> RskToTapTransferBatch | None:
        current_batch = (
            dbsession.query(
                RskToTapTransferBatch,
            )
            .filter(
                RskToTapTransferBatch.status != RskToTapTransferBatchStatus.FINALIZED,
            )
            .order_by(
                RskToTapTransferBatch.id.asc(),
            )
            .first()
        )
        if current_batch:
            return current_batch

        # Create a new batch
        transfers = (
            dbsession.query(RskToTapTransfer)
            .filter(
                RskToTapTransfer.transfer_batch_id.is_(None),
            )
            .order_by(RskToTapTransfer.counter)
            .limit(
                self.batch_limit,
            )
            .all()
        )
        if not transfers:
            return None
        current_batch = RskToTapTransferBatch(
            transfers=transfers,
            status=RskToTapTransferBatchStatus.CREATED,
        )
        dbsession.add(current_batch)
        dbsession.flush()
        return current_batch

    def get_transfers_by_address(self, address: str):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)

            logger.info("Getting transfer status for address %s", address)

            transfers = (
                dbsession.query(
                    RskToTapTransfer.sender_rsk_address,
                    RskToTapTransfer.db_id,
                    RskToTapTransferBatch.status,
                )
                .select_from(RskToTapTransfer)
                .join(RskToTapTransferBatch)
                .filter(RskToTapTransfer.sender_rsk_address == address)
                .all()
            )

            logger.info("Got transfers: %s", transfers)

            return transfers
