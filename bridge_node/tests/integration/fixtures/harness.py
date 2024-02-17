import os
import logging
import subprocess
import time
import shutil

import pytest
import json

from bridge.api_client import BridgeAPIClient
from ..constants import NODE1_API_BASE_URL, PROJECT_BASE_DIR

logger = logging.getLogger(__name__)

NO_START_HARNESS = os.environ.get("NO_START_HARNESS") == "1"
HARNESS_VERBOSE = os.environ.get("HARNESS_VERBOSE") == "1"


class IntegrationTestHarness:
    MAX_START_WAIT_TIME_S = 120
    WAIT_INTERVAL_S = 5
    BITCOIND_CONTAINER = 'bitcoind-regtest'
    FEDERATORS = (
        'alice',
        'bob',
    )
    EXTRA_LND_CONTAINERS = [
        'carol-lnd',
        'user-lnd',
    ]
    VOLUMES_PATH = PROJECT_BASE_DIR / "volumes"

    def __init__(self, *, verbose=False):
        self._api_client = BridgeAPIClient(NODE1_API_BASE_URL)
        self.verbose = verbose

    def start(self):
        if self.is_started():
            raise ValueError(
                "Integration test docker compose harness is already started. "
                "To disable automatic harness start, set the env var NO_START_HARNESS=1"
            )

        logger.info("Starting integration test harness")
        self._clean()
        logger.info("Starting docker compose")
        self._run_docker_compose_command("up", "--build", "--detach")

        self._bitcoind_lnd_init()

        logger.info("Waiting for bridge node to start")
        start_time = time.time()
        while time.time() - start_time < self.MAX_START_WAIT_TIME_S:
            if self.is_started():
                logger.info("Bridge node started.")
                break
            time.sleep(self.WAIT_INTERVAL_S)
        else:
            raise TimeoutError(
                f"Bridge node did not start in {self.MAX_START_WAIT_TIME_S} seconds"
            )
        logger.info("Integration test harness started.")

    def stop(self):
        logger.info("Stopping integration test harness")
        logger.info("Stopping docker compose")
        self._run_docker_compose_command("down")
        logger.info("Stopped.")

    def is_started(self):
        return self._api_client.is_healthy()

    def _clean(self):
        # DB data directory needs to be cleaned before this can be started
        # TODO: maybe it should not have a persistent volume in the dev compose after all!
        db_data_dir = PROJECT_BASE_DIR / "db_data"
        if db_data_dir.exists():
            logger.info("Cleaning db_data directory %s", db_data_dir.absolute())
            shutil.rmtree(db_data_dir)
        volumes_dir = PROJECT_BASE_DIR / "volumes"
        if volumes_dir.exists():
            logger.info("Cleaning volumes directory %s", volumes_dir.absolute())
            shutil.rmtree(volumes_dir)

    def _bitcoind_lnd_init(self):
        logger.info("bitcoind/lnd init")
        logger.info("Waiting for bitcoin rpc startup")
        time.sleep(5)  # Quick and dirty, just sleep x amount of time
        logger.info("Mining initial btc block")
        # NOTE: the btc address is random and not really important
        self._run_docker_compose_command(
            "exec",
            self.BITCOIND_CONTAINER,
            "bitcoin-cli", "-datadir=/home/bitcoin/.bitcoin", "-regtest",
            "generatetoaddress", "1", "bcrt1qtxysk2megp39dnpw9va32huk5fesrlvutl0zdpc29asar4hfkrlqs2kzv5",
            verbose=False,
        )
        logger.info("Giving some time for LND nodes to start and connect to bitcoind.")
        time.sleep(2)
        lnd_containers = [f'{f}-lnd' for f in self.FEDERATORS]
        lnd_containers.extend(self.EXTRA_LND_CONTAINERS)
        for lnd_container in lnd_containers:
            logger.info("Depositing funds to %s", lnd_container)
            # Try multiple times because maybe the lnd node is not yet started
            for tries_left in range(20, 0, -1):
                try:
                    addr_response = self._capture_docker_compose_output(
                        "exec", "-u", "lnd", lnd_container,
                        "/opt/lnd/lncli", "-n", "regtest", "newaddress", "p2tr",
                    )
                    break
                except Exception as e:
                    if tries_left <= 1:
                        raise e
                    logger.info(
                        "LND node %s not yet started, retrying in 2 seconds...",
                        lnd_container,
                    )
                    time.sleep(2)
            else:
                raise Exception("should not get here")
            addr = json.loads(addr_response)['address']
            logger.info("Mining 101 blocks to %s's addr %s", lnd_container, addr)
            self._run_docker_compose_command(
                "exec", self.BITCOIND_CONTAINER,
                "bitcoin-cli", "-datadir=/home/bitcoin/.bitcoin", "-regtest",
                "generatetoaddress", "101", addr,
                verbose=False,
            )
            logger.info("Mined.")

        logger.info("Waiting for macaroons to be available (start of tapd)")
        for _ in range(20):
            ok = True
            for federator_id in self.FEDERATORS:
                tap_container = f'{federator_id}-tap'
                macaroon_path = self.VOLUMES_PATH / "tapd" / tap_container / "data" / "regtest" / "admin.macaroon"
                if not macaroon_path.exists():
                    logger.info(
                        "macaroon for %s not available",
                        tap_container,
                    )
                    ok = False
            if ok:
                break
            logger.info("all macaroons not available, retrying in 2 seconds...")
            time.sleep(2)
        else:
            raise TimeoutError("Macaroons not available after waiting")

        logger.info("bitcoind/lnd init done")

    def _run_docker_compose_command(self, *args, verbose=None):
        if verbose is None:
            verbose = self.verbose
        extra_kwargs = {}
        if not verbose:
            extra_kwargs.update(
                dict(
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )

        subprocess.run(
            ("docker-compose", "-f", "docker-compose.dev.yaml") + args,
            cwd=PROJECT_BASE_DIR,
            check=True,
            **extra_kwargs,
        )

    def _capture_docker_compose_output(self, *args):
        return subprocess.check_output(
            ("docker-compose", "-f", "docker-compose.dev.yaml") + args,
            cwd=PROJECT_BASE_DIR,
        )

    def run_hardhat_json_command(self, *args):
        return json.loads(
            self._capture_docker_compose_output(
                "exec", "hardhat", "npx", "hardhat", "--network", "localhost", *args
            )
        )


@pytest.fixture(scope="session", autouse=True)
def harness(request) -> IntegrationTestHarness:
    harness = IntegrationTestHarness(verbose=HARNESS_VERBOSE)
    if NO_START_HARNESS:
        logger.info("Skipping harness autostart because NO_START_HARNESS=1")
    else:
        request.addfinalizer(harness.stop)
        harness.start()
    return harness
