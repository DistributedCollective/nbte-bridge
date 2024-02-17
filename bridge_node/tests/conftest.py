import os
import subprocess
import sys
import pathlib

import pytest
from sqlalchemy.orm import Session

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
THIS_DIR = pathlib.Path(__file__).parent
INTEGRATION_TEST_DIR = THIS_DIR / "integration"


def pytest_collection_modifyitems(config, items):
    for item in items:
        item_path = pathlib.Path(item.fspath)
        # Mark tests in the integration/ dir as integration tests
        if item_path.is_relative_to(INTEGRATION_TEST_DIR):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def logger():
    import logging

    logging.basicConfig(level=logging.DEBUG)
    return logging.getLogger("tester")


@pytest.fixture(scope="session")
def setup_db(logger):
    try:
        subprocess.run(
            [sys.executable, "-malembic", "-nlocal_testing_against_docker", "upgrade", "head"],
            check=True,
            cwd=BASE_DIR,
        )
    except subprocess.CalledProcessError as e:
        logger.exception(
            "Failed to run alembic upgrade head."
            "Suggest cleaning (or creating) the test database. "
        )
        raise e from None


# @pytest.fixture
# def dbsession() -> Session:
#     # TODO
#     pass
