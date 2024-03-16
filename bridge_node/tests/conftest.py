import os
import pathlib

import pytest
from sqlalchemy import create_engine

from bridge.common.models.meta import Base
from . import services

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
THIS_DIR = pathlib.Path(__file__).parent
INTEGRATION_TEST_DIR = THIS_DIR / "integration"

ALICE_EVM_PRIVATE_KEY = "0x9a9a640da1fc0181e43a9ea00b81878f26e1678e3e246b25bd2835783f2be181"

DEV_DB_NAME = "nbte_tmp_test"


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
def user_ord(request):
    return services.OrdService(
        service="user-ord",
        ord_api_url="http://localhost:3080",
        request=request,
    )


@pytest.fixture(scope="module")
def alice_ord(request):
    return services.OrdService(
        service="alice-ord",
        ord_api_url="http://localhost:3080",
        request=request,
    )


@pytest.fixture(scope="module")
def dbengine(postgres):
    postgres.cli(f"DROP DATABASE IF EXISTS {DEV_DB_NAME};")
    postgres.cli(f"CREATE DATABASE {DEV_DB_NAME};")

    engine = create_engine(postgres.dsn_outside_docker, echo=False)
    Base.metadata.create_all(engine)
    return engine


# TODO: we can have something like this but not necessarily yet
# @pytest.fixture(scope="module")
# def dbsession(engine):
#     session = Session(bind=engine)
#     yield session
#     session.rollback()
