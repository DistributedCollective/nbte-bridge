import os
import pathlib
import logging

import pytest
from sqlalchemy import create_engine

from bridge.common.models.meta import Base
from . import services

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
THIS_DIR = pathlib.Path(__file__).parent
INTEGRATION_TEST_DIR = THIS_DIR / "integration"
DEV_DB_NAME = "nbte_tmp_test"

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption(
        "--keep-containers",
        action="store_true",
        help="Keep docker compose containers running between tests",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        item_path = pathlib.Path(item.fspath)
        # Mark tests in the integration/ dir as integration tests
        if item_path.is_relative_to(INTEGRATION_TEST_DIR):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def postgres(request):
    return services.PostgresService(request)


@pytest.fixture(scope="module")
def hardhat(request):
    return services.HardhatService(request)


@pytest.fixture(scope="module")
def bitcoind(request):
    return services.BitcoindService(request)


@pytest.fixture(scope="module")
def ord(request):
    # We'll just roll with one ord service for the whole bridge and the user in tests
    # It supports different wallets anyway
    # This fixture shadows the built-in name `ord`, but who uses it anyway.
    return services.OrdService(request)


@pytest.fixture(scope="module")
def dbengine(postgres):
    logger.info("Dropping and recreating test database %s", DEV_DB_NAME)
    postgres.cli(f"DROP DATABASE IF EXISTS {DEV_DB_NAME}")
    postgres.cli(f"CREATE DATABASE {DEV_DB_NAME}")

    dsn = postgres.get_db_dsn(DEV_DB_NAME)
    engine = create_engine(dsn, echo=False)
    logger.info("Creating all models from metadata")
    Base.metadata.create_all(engine)
    return engine


# TODO: we can have something like this but not necessarily yet
# @pytest.fixture(scope="module")
# def dbsession(engine):
#     session = Session(bind=engine)
#     yield session
#     session.rollback()
