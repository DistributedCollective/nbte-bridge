from bridge.bridges.tap_rsk.models import (
    RskToTapTransferBatch,
    RskToTapTransferBatchStatus,
    TapToRskTransferBatch,
    TapToRskTransferBatchStatus,
)


def test_transfer_batch_init(dbsession):
    with dbsession.begin():
        batch = RskToTapTransferBatch()
        dbsession.add(batch)
        dbsession.flush()
        assert batch.status == RskToTapTransferBatchStatus.CREATED

        batch = TapToRskTransferBatch()
        batch.hash = batch.compute_hash()
        dbsession.add(batch)
        dbsession.flush()
        assert batch.status == TapToRskTransferBatchStatus.CREATED
