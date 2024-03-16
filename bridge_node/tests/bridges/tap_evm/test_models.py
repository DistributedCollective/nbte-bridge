import pytest
from sqlalchemy.orm.session import Session

from bridge.bridges.tap_rsk.models import (
    RskToTapTransferBatch,
    RskToTapTransferBatchStatus,
    TapToRskTransferBatch,
    TapToRskTransferBatchStatus,
)


@pytest.fixture
def dbsession(dbengine):
    session = Session(bind=dbengine)
    yield session
    session.rollback()


def test_transfer_batch_init(dbsession):
    batch = RskToTapTransferBatch()
    dbsession.add(batch)
    dbsession.flush()
    assert batch.status == RskToTapTransferBatchStatus.CREATED

    batch = TapToRskTransferBatch()
    batch.hash = batch.compute_hash()
    dbsession.add(batch)
    dbsession.flush()
    assert batch.status == TapToRskTransferBatchStatus.CREATED
