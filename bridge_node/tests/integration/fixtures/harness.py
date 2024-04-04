import os
import logging
import subprocess
import time
import shutil

import pytest
import json

from bridge.api_client import BridgeAPIClient
from ..constants import NODE1_API_BASE_URL
from ...compose import ENV_FILE as COMPOSE_ENV_FILE, COMPOSE_FILE, PROJECT_BASE_DIR
from ...services import BitcoindService

logger = logging.getLogger(__name__)

NO_START_HARNESS = os.environ.get("NO_START_HARNESS") == "1"
HARNESS_VERBOSE = os.environ.get("HARNESS_VERBOSE") == "1"
SKIP_TAP_BRIDGE = os.environ.get("HARNESS_SKIP_TAP_BRIDGE") == "1"
SKIP_RUNE_BRIDGE = os.environ.get("HARNESS_SKIP_RUNE_BRIDGE") == "1"
INTEGRATION_TEST_ENV_FILE = PROJECT_BASE_DIR / "env.integrationtest"
assert INTEGRATION_TEST_ENV_FILE.exists(), f"Missing {INTEGRATION_TEST_ENV_FILE}"

DOCKER_COMPOSE_BASE_ARGS = (
    "docker",
    "compose",
    "-f",
    str(COMPOSE_FILE),
    "--env-file",
    str(COMPOSE_ENV_FILE),
    "--env-file",
    str(INTEGRATION_TEST_ENV_FILE),
)


class IntegrationTestHarness:
    MAX_START_WAIT_TIME_S = 220
    WAIT_INTERVAL_S = 5
    BITCOIND_CONTAINER = "bitcoind"
    FEDERATORS = (
        "alice",
        "bob",
        # 'carol',
    )
    EXTRA_LND_CONTAINERS = [
        "user-lnd",
    ]
    VOLUMES_PATH = PROJECT_BASE_DIR / "volumes"
    # 1 of 3 wallet based on values in docker-compose.dev.yml. Needs to be changed when the
    # number of signers, or the keys, change
    RUNE_BRIDGE_MULTISIG_DESCRIPTOR = (
        "wsh(sortedmulti(1,"
        "tpubD6NzVbkrYhZ4WokHnVXX8CVBt1S88jkmeG78yWbLxn7Wd89nkNDe2J8b6opP4K38mRwXf9d9VVN5uA58epPKjj584R1rnDDbk6oHUD1MoWD/13/0/0/*,"
        "tpubD6NzVbkrYhZ4WpZfRZip3ALqLpXhHUbe6UyG8iiTzVDuvNUyysyiUJWejtbszZYrDaUM8UZpjLmHyvtV7r1QQNFmTqciAz1fYSYkw28Ux6y/13/0/0/*,"
        "tpubD6NzVbkrYhZ4WQZnWqU8ieBsujhoZKZLF6wMvTApJ4ZiGmipk481DyM2su3y5BDeB9fFLwSmmmsGDGJum79he2fnuQMnpWhe3bGir7Mf4uS/13/0/0/*"
        "))#jyn3fuhd"
    )
    # this also needs changing when the above changes
    RUNE_BRIDGE_MULTISIG_CHANGE_ADDRESS = (
        "bcrt1qh3j9z0tsxpqc07caeehn3j0q7mfmq0stcfacudlcndpssv48lnaqs0vfw8"
    )

    bitcoind: BitcoindService

    def __init__(self, *, verbose=False):
        self._api_client = BridgeAPIClient(NODE1_API_BASE_URL)
        self.verbose = verbose
        self.bitcoind = BitcoindService()

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

        self._init_environment()

        logger.info("Waiting for bridge node to start")
        start_time = time.time()
        while time.time() - start_time < self.MAX_START_WAIT_TIME_S:
            if self.is_started():
                logger.info("Bridge node started.")
                break
            time.sleep(self.WAIT_INTERVAL_S)
        else:
            raise TimeoutError(f"Bridge node did not start in {self.MAX_START_WAIT_TIME_S} seconds")
        logger.info("Integration test harness started.")

    def stop(self):
        logger.info("Stopping integration test harness")
        logger.info("Stopping docker compose")
        self._run_docker_compose_command("down", "-v")
        logger.info("Stopped.")

    def is_started(self):
        return self._api_client.is_healthy()

    def is_any_service_started(self):
        # docker compose ps --format json returns newline-separated json objects for each service.
        # if not services are started, it returns an empty string
        ps_output = self._capture_docker_compose_output("ps", "--format", "json")
        return bool(ps_output.strip())

    def _clean(self):
        # Currently *named* volumes are removed automatically by docker compose down -v
        # bind mounts still need cleaning in case there is something we want to clean.
        # Another option is to get rid of all the bind mounts and use named volumes only.
        # TODO: maybe mount everything as named volumes
        if self.VOLUMES_PATH.exists():
            for volume_dir in list(self.VOLUMES_PATH.iterdir()):
                logger.info("Cleaning volume directory %s", volume_dir.absolute())
                shutil.rmtree(volume_dir)

    def _init_environment(self):
        """
        Does environment initialization, such as creating wallets and mining initial bitcoin blocks
        """
        logger.info("Initializing the environment")

        logger.info("Waiting for bitcoin rpc startup")
        self.bitcoind.wait()
        logger.info("Mining initial btc block (tapd/lnd won't start before)")
        self.bitcoind.mine()

        if SKIP_TAP_BRIDGE:
            logger.info("Skipping tap bridge initialization because HARNESS_SKIP_TAP_BRIDGE=1")
        else:
            self._init_tap_bridge()
        if SKIP_RUNE_BRIDGE:
            logger.info("Skipping rune bridge initialization because HARNESS_SKIP_RUNE_BRIDGE=1")
        else:
            self._init_rune_bridge()

        # BTC initial blocks
        logger.info("Mining 100 blocks to a random address to see mining rewards")
        self.bitcoind.mine(100)

        logger.info("Environment initialization done")

    def _init_tap_bridge(self):
        logger.info("Initializing the tap bridge")
        logger.info("Giving some time for LND nodes to start and connect to bitcoind.")
        time.sleep(2)
        lnd_containers = [f"{f}-lnd" for f in self.FEDERATORS]
        lnd_containers.extend(self.EXTRA_LND_CONTAINERS)
        for lnd_container in lnd_containers:
            logger.info("Depositing funds to %s", lnd_container)
            # Try multiple times because maybe the lnd node is not yet started
            for tries_left in range(20, 0, -1):
                try:
                    addr_response = self._capture_docker_compose_output(
                        "exec",
                        "-u",
                        "lnd",
                        lnd_container,
                        "/opt/lnd/lncli",
                        "-n",
                        "regtest",
                        "newaddress",
                        "p2tr",
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
            addr = json.loads(addr_response)["address"]
            logger.info("Mining 2 blocks to %s's addr %s", lnd_container, addr)
            self.bitcoind.mine(2, address=addr)
            logger.info("Mined.")

        logger.info("Waiting for macaroons to be available (start of tapd)")
        for _ in range(20):
            ok = True
            for federator_id in self.FEDERATORS:
                tap_container = f"{federator_id}-tap"
                macaroon_path = (
                    self.VOLUMES_PATH
                    / "tapd"
                    / tap_container
                    / "data"
                    / "regtest"
                    / "admin.macaroon"
                )
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

    def _init_rune_bridge(self):
        # Rune bridge wallets
        any_created = False
        for federator in self.FEDERATORS:
            wallet_name = f"{federator}-runes"
            wallet, created = self.bitcoind.load_or_create_wallet(
                wallet_name,
                blank=True,
                disable_private_keys=True,
            )
            if created:
                logger.info("Created wallet %s, importing descriptors", wallet_name)
                any_created = True
                wallet.rpc.call(
                    "importdescriptors",
                    [
                        {
                            "desc": self.RUNE_BRIDGE_MULTISIG_DESCRIPTOR,
                            "timestamp": "now",
                            "range": 10000,
                        },
                    ],
                )
            else:
                logger.info("Wallet %s already created", wallet_name)
        if any_created:
            logger.info(
                "Funding rune multisig wallet (address %s)",
                self.RUNE_BRIDGE_MULTISIG_CHANGE_ADDRESS,
            )
            self.bitcoind.mine(2, address=self.RUNE_BRIDGE_MULTISIG_CHANGE_ADDRESS)

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
            DOCKER_COMPOSE_BASE_ARGS + args,
            cwd=PROJECT_BASE_DIR,
            check=True,
            **extra_kwargs,
        )

    def _capture_docker_compose_output(self, *args):
        return subprocess.check_output(
            DOCKER_COMPOSE_BASE_ARGS + args,
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
        keep_containers = request.config.getoption("--keep-containers")
        if keep_containers and harness.is_any_service_started():
            logger.info(
                "Pytest is running with --keep-containers and some docker-compose services have already started. "
                "Shutting down everything before stating the integration test harness."
            )
            harness.stop()

        # The harness should in theory not mess up --keep-containers, but I'm not 100% sure.
        # Lets at least stop hardhat interval mining
        def finalizer():
            if keep_containers:
                logger.info(
                    "Not stopping harness because --keep-containers is on, but enabling automining again"
                )
                harness.run_hardhat_json_command("set-mining-interval", "0")
            else:
                harness.stop()

        request.addfinalizer(finalizer)
        harness.start()
    return harness
