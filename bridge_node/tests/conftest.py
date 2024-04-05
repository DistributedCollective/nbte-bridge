import os
import pathlib
import logging
import dataclasses

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bridge.common.models import load_models
from bridge.common.models.meta import Base
import bitcointx
from . import services

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
THIS_DIR = pathlib.Path(__file__).parent
INTEGRATION_TEST_DIR = THIS_DIR / "integration"
DEV_DB_NAME = "nbte_tmp_test"

logger = logging.getLogger(__name__)

# We need to patch this somewhere so let's do it here where it's automatically active
# for all tests. Note that threads make it fail.
bitcointx.select_chain_params("bitcoin/regtest")


@dataclasses.dataclass
class Flags:
    keep_containers: bool


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
def flags(request) -> Flags:
    return Flags(
        keep_containers=request.config.getoption("--keep-containers"),
    )


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
def ord(request, bitcoind):
    # We'll just roll with one ord service for the whole bridge and the user in tests
    # It supports different wallets anyway
    # This fixture shadows the built-in name `ord`, but who uses it anyway.
    return services.OrdService(bitcoind=bitcoind, request=request)


@pytest.fixture(scope="module")
def dbengine(postgres):
    load_models()
    logger.info("Dropping and recreating test database %s", DEV_DB_NAME)
    postgres.cli(f"DROP DATABASE IF EXISTS {DEV_DB_NAME}")
    postgres.cli(f"CREATE DATABASE {DEV_DB_NAME}")

    dsn = postgres.get_db_dsn(DEV_DB_NAME)
    engine = create_engine(dsn, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture()  # NOTE: scope is "test" here to start each test with a fresh DB
def dbsession(dbengine):
    logger.info("Creating all models from metadata")
    Base.metadata.create_all(dbengine)
    yield Session(bind=dbengine, autobegin=False)
    logger.info("Dropping all models from metadata")
    Base.metadata.drop_all(dbengine)
