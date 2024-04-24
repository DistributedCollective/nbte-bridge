import json
import logging
import os
import shutil
import time

import pytest

from bridge.api_client import BridgeAPIClient

from ... import compose
from ...services import BitcoindService
from ..constants import NODE1_API_BASE_URL

logger = logging.getLogger(__name__)

NO_START_HARNESS = os.environ.get("NO_START_HARNESS") == "1"
HARNESS_VERBOSE = os.environ.get("HARNESS_VERBOSE") == "1"
SKIP_TAP_BRIDGE = os.environ.get("HARNESS_SKIP_TAP_BRIDGE") == "1"
SKIP_RUNE_BRIDGE = os.environ.get("HARNESS_SKIP_RUNE_BRIDGE") == "1"

INTEGRATION_TEST_ENV_FILE = compose.PROJECT_BASE_DIR / "env.integrationtest"
assert INTEGRATION_TEST_ENV_FILE.exists(), f"Missing {INTEGRATION_TEST_ENV_FILE}"

INTEGRATION_COMPOSE_BASE_ARGS = ("--env-file", str(INTEGRATION_TEST_ENV_FILE))


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
    VOLUMES_PATH = compose.PROJECT_BASE_DIR / "volumes"
    # 1 of 3 wallet based on values in docker-compose.dev.yml. Needs to be changed when the
    # number of signers, or the keys, change
    RUNE_BRIDGE_MULTISIG_DESCRIPTOR = (
        # BIG STRING WOO WOO
        "wsh(sortedmulti(2,tpubD6NzVbkrYhZ4WokHnVXX8CVBt1S88jkmeG78yWbLxn7Wd89nkNDe2J8b6opP4K38mRwXf9d9VVN5uA58epPKjj584R1rnDDbk6oHUD1MoWD/13/0/0/*,tpubD6NzVbkrYhZ4WpZfRZip3ALqLpXhHUbe6UyG8iiTzVDuvNUyysyiUJWejtbszZYrDaUM8UZpjLmHyvtV7r1QQNFmTqciAz1fYSYkw28Ux6y/13/0/0/*,tpubD6NzVbkrYhZ4WQZnWqU8ieBsujhoZKZLF6wMvTApJ4ZiGmipk481DyM2su3y5BDeB9fFLwSmmmsGDGJum79he2fnuQMnpWhe3bGir7Mf4uS/13/0/0/*))#qqwc9q36"
    )
    # this also needs changing when the above changes
    RUNE_BRIDGE_MULTISIG_CHANGE_ADDRESS = "bcrt1qenkjz7gt2jtys84dwdh75696arc85ld7dl85p7jd77ksxds55tjqtl627a"

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

        self._run_docker_compose_command("up", "--build", "--wait", "--wait-timeout", str(self.MAX_START_WAIT_TIME_S))

        self._init_environment()

        logger.info("Integration test harness started.")

    def stop(self):
        logger.info("Stopping integration test harness")
        logger.info("Stopping docker compose")

        self._run_docker_compose_command("down", "--volumes")

        logger.info("Stopped.")

    def is_started(self):
        return self._api_client.is_healthy()

    def is_any_service_started(self):
        # docker compose ps --services returns the running services separated by newlines.
        # if not services are started, it returns an empty string
        ps_output = self._run_docker_compose_command("ps", "--services", verbose=True)[0]
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

            addr_response = self._run_docker_compose_command(
                "exec",
                "-u",
                "lnd",
                lnd_container,
                "/opt/lnd/lncli",
                "-n",
                "regtest",
                "newaddress",
                "p2tr",
            )[0]

            addr = json.loads(addr_response)["address"]

            logger.info("Mining 2 blocks to %s's addr %s", lnd_container, addr)
            self.bitcoind.mine(2, address=addr)
            logger.info("Mined.")

        logger.info("Checking macaroon availability (start of tapd)")
        for federator_id in self.FEDERATORS:
            tap_container = f"{federator_id}-tap"
            macaroon_path = self.VOLUMES_PATH / "tapd" / tap_container / "data" / "regtest" / "admin.macaroon"
            assert macaroon_path.exists()

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

        command = INTEGRATION_COMPOSE_BASE_ARGS + args
        proc = compose.run_command(*command, quiet=not verbose, capture=True)

        return self._decode_stream(proc.stdout), self._decode_stream(proc.stderr), proc.returncode

    def _decode_stream(self, stream):
        return stream.decode("utf-8") if stream else None

    def run_hardhat_json_command(self, *args):
        output = self._run_docker_compose_command("exec", "hardhat", "npx", "hardhat", "--network", "localhost", *args)[
            0
        ]

        return json.loads(output)


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
                logger.info("Not stopping harness because --keep-containers is on, but enabling automining again")
                harness.run_hardhat_json_command("set-mining-interval", "0")
            else:
                harness.stop()

        request.addfinalizer(finalizer)
        harness.start()

    return harness
