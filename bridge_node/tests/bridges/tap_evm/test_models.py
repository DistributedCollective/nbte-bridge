import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm.session import Session
import subprocess
from bridge.common.models.meta import Base
from bridge.bridges.tap_rsk.models import (
    RskToTapTransferBatch,
    RskToTapTransferBatchStatus,
    TapToRskTransferBatch,
    TapToRskTransferBatchStatus,
)

DEV_DB_NAME = "nbte_tmp_test"


@pytest.fixture(scope="session")
def engine():
    subprocess.check_output(['dropdb', "--if-exists", DEV_DB_NAME])
    subprocess.check_output(['createdb', DEV_DB_NAME])
    engine = create_engine(f"postgresql:///{DEV_DB_NAME}", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def dbsession(engine):
    session = Session(bind=engine)
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

