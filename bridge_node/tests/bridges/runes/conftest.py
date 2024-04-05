import dataclasses
import logging
import time
from types import SimpleNamespace

import pytest
from anemic.ioc import (
    Container,
    FactoryRegistry,
)
from sqlalchemy.orm import (
    Session,
    sessionmaker,
)
from web3.contract import Contract

from bridge.bridges.runes.bridge import RuneBridge
from bridge.bridges.runes.config import (
    RuneBridgeConfig,
    RuneBridgeSecrets,
)
from bridge.bridges.runes.evm import load_rune_bridge_abi
from bridge.bridges.runes.service import RuneBridgeService
from bridge.bridges.runes.wiring import wire_rune_bridge
from bridge.common.ord.multisig import OrdMultisig
from bridge.common.services.key_value_store import KeyValueStore
from bridge.common.services.transactions import TransactionManager
from .bridge_util import RuneBridgeUtil
from ...mock_network import MockNetwork
from ...services import (
    BitcoindService,
    HardhatService,
    OrdService,
    OrdWallet,
)
from ...services.hardhat import EVMWallet
from ...utils.bitcoin import generate_extended_keypair
from ...utils.timing import measure_time

logger = logging.getLogger(__name__)


MODULE_SETUP_CACHE_KEY = "runes_module_setup"


@dataclasses.dataclass
class CachedModuleSetup:
    alice_evm_private_key: str
    user_evm_private_key: str
    rune_bridge_contract_address: str
    root_ord_wallet_name: str
    root_ord_wallet_address: str
    user_ord_wallet_name: str
    user_ord_wallet_address: str
    snapshot_id: str


@pytest.fixture(scope="module")
def runes_module_setup(
    hardhat,
    ord,
    request,
    flags,
):
    cache = request.config.cache
    cached_setup: CachedModuleSetup | None = None
    if cache and not flags.keep_containers:
        # Whatever is in the cache doesn't work for us if --keep-containers = False, so remove it
        cache.set(MODULE_SETUP_CACHE_KEY, None)
    if cache and flags.keep_containers:
        logger.info("Attempting to use cache")
        cached_setup_dict = cache.get(MODULE_SETUP_CACHE_KEY, None)
        if cached_setup_dict:
            try:
                cached_setup = CachedModuleSetup(**cached_setup_dict)
            except Exception:
                logger.exception("Failed to load cached setup dataclass")
                logger.info(
                    "The above exception is here only for debug purposes and can be ignored. "
                    "Falling back to re-deploying everything"
                )

        if cached_setup:
            cache.set(
                MODULE_SETUP_CACHE_KEY, None
            )  # remove it, so that it's not accidentally used again
            logger.info(
                "Found cached setup, attempting to restore snapshot %r", cached_setup.snapshot_id
            )
            try:
                hardhat.revert(cached_setup.snapshot_id)
            except Exception:
                logger.info(
                    "Restoring snapshot %r failed (hardhat probably restarted), falling back to re-deploying everything",
                    cached_setup.snapshot_id,
                )
                cached_setup = None
            else:
                logger.info("Restored snapshot successfully")

    if cached_setup:
        logger.info("Reusing cached setup")
        alice_evm_wallet = EVMWallet(
            account=hardhat.web3.eth.account.from_key(cached_setup.alice_evm_private_key),
            name="alice",
        )
        user_evm_wallet = EVMWallet(
            account=hardhat.web3.eth.account.from_key(cached_setup.user_evm_private_key),
            name="alice",
        )
        rune_bridge_address = cached_setup.rune_bridge_contract_address

        root_ord_wallet = OrdWallet(
            ord=ord,
            name=cached_setup.root_ord_wallet_name,
            addresses=[cached_setup.root_ord_wallet_address],
        )
        user_ord_wallet = OrdWallet(
            ord=ord,
            name=cached_setup.user_ord_wallet_name,
            addresses=[cached_setup.user_ord_wallet_address],
        )
    else:
        # This only needs to be done once, after which we can use EVM snapshots etc
        with measure_time("create-evm-wallets"):
            alice_evm_wallet = hardhat.create_test_wallet("alice", impersonate=False)
            user_evm_wallet = hardhat.create_test_wallet("user")

        with measure_time("deploy-access-control"):
            access_control_deployment = hardhat.run_json_command(
                "deploy-access-control",
                "--federators",
                ",".join([alice_evm_wallet.account.address]),
            )

        with measure_time("deploy-btc-address-validator"):
            address_validator_deployment = hardhat.run_json_command(
                "deploy-btc-address-validator",
                "--access-control",
                access_control_deployment["address"],
                "--bech32-prefix",
                "bcrt1",
                "--non-bech32-prefixes",
                "m,n,2",
            )

        with measure_time("runes-deploy-regtest"):
            deployment = hardhat.run_json_command(
                "runes-deploy-regtest",
                "--access-control",
                access_control_deployment["address"],
                "--address-validator",
                address_validator_deployment["address"],
            )
        rune_bridge_address = deployment["addresses"]["RuneBridge"]

        with measure_time("create ord wallets"):
            root_ord_wallet = ord.create_test_wallet("root-ord")  # used for funding other wallets
            root_ord_wallet.get_receiving_address()  # will cache it
            user_ord_wallet = ord.create_test_wallet("user-ord")  # used by the "end user"
            user_ord_wallet.get_receiving_address()  # will cache it

    rune_bridge_contract = hardhat.web3.eth.contract(
        address=rune_bridge_address,
        abi=load_rune_bridge_abi("RuneBridge"),
    )

    if cache and flags.keep_containers:
        logger.info("Snapshotting runes_module_setup and storing the setup in cache")
        with measure_time("snapshotting runes_module_setup"):
            snapshot_id = hardhat.snapshot()
        cached_setup = CachedModuleSetup(
            alice_evm_private_key=alice_evm_wallet.account.key.hex(),
            user_evm_private_key=user_evm_wallet.account.key.hex(),
            rune_bridge_contract_address=rune_bridge_address,
            root_ord_wallet_name=root_ord_wallet.name,
            root_ord_wallet_address=root_ord_wallet.get_receiving_address(),
            user_ord_wallet_name=user_ord_wallet.name,
            user_ord_wallet_address=user_ord_wallet.get_receiving_address(),
            snapshot_id=snapshot_id,
        )
        cache.set(MODULE_SETUP_CACHE_KEY, dataclasses.asdict(cached_setup))

    return SimpleNamespace(
        alice_evm_wallet=alice_evm_wallet,
        user_evm_wallet=user_evm_wallet,
        rune_bridge_contract=rune_bridge_contract,
        root_ord_wallet=root_ord_wallet,
        user_ord_wallet=user_ord_wallet,
    )


@pytest.fixture()
def runes_setup(
    hardhat: HardhatService,
    bitcoind: BitcoindService,
    ord: OrdService,
    dbengine,
    runes_module_setup,
):
    start = time.time()
    snapshot_id = hardhat.snapshot()

    # Use data that's slow to create from the module setup
    root_ord_wallet = runes_module_setup.root_ord_wallet
    user_ord_wallet = runes_module_setup.user_ord_wallet
    alice_evm_wallet = runes_module_setup.alice_evm_wallet
    user_evm_wallet = runes_module_setup.user_evm_wallet
    rune_bridge_contract = runes_module_setup.rune_bridge_contract

    # Fund ord wallets every time
    with measure_time("fund ord wallets"):
        bitcoind.fund_wallets(root_ord_wallet, user_ord_wallet)

    # NETWORK

    with measure_time("create network"):
        alice_network = MockNetwork(node_id="alice", leader=True)
        bob_network = MockNetwork(node_id="bob")
        carol_network = MockNetwork(node_id="carol")

        alice_network.add_peers([bob_network, carol_network])
        bob_network.add_peers([alice_network, carol_network])
        carol_network.add_peers([alice_network, bob_network])

    with measure_time("create transaction manager"):
        transaction_registry = FactoryRegistry("transaction")
        transaction_registry.register(
            interface=KeyValueStore,
            factory=KeyValueStore,
        )
        session_factory = sessionmaker(bind=dbengine, autobegin=False)
        transaction_registry.register(
            interface=Session,
            factory=lambda _: session_factory(),
        )
        transaction_manager = TransactionManager(
            global_container=Container(FactoryRegistry("global")),
            transaction_registry=transaction_registry,
        )

    # TODO: make the wallet 2-of-3
    with measure_time("create multisig"):
        bridge_multisig_wallet = bitcoind.create_test_wallet(
            "runebridge-multisig",
            blank=True,
            disable_private_keys=True,
        )
    with measure_time("create keypairs"):
        alice_xprv, alice_xpub = generate_extended_keypair()
        bob_xprv, bob_xpub = generate_extended_keypair()

    # TODO: not sure if we should use wire_rune_bridge
    # or directly instantiate it. Directly instantiating is more explicit and suits
    # test, but on the other hand, with wire_rune_bridge we don't have to care
    # about the internals so much, and we're actually testing how it's wired
    # in real life
    with measure_time("wiring"):
        alice_wiring = wire_rune_bridge(
            config=RuneBridgeConfig(
                bridge_id="test-runebridge",
                rune_bridge_contract_address=rune_bridge_contract.address,
                evm_rpc_url=hardhat.rpc_url,
                btc_rpc_wallet_url=bitcoind.get_wallet_rpc_url(bridge_multisig_wallet.name),
                btc_num_required_signers=1,
                ord_api_url=ord.api_url,
                evm_block_safety_margin=0,
                evm_default_start_block=1,
            ),
            secrets=RuneBridgeSecrets(
                evm_private_key=alice_evm_wallet.account.key,
                btc_master_xpriv=str(alice_xprv),
                btc_master_xpubs=[str(alice_xpub), str(bob_xpub)],
            ),
            network=alice_network,
            transaction_manager=transaction_manager,
        )

    # Ensure bitcoind sees the wallet
    with measure_time("import descriptors"):
        alice_wiring.multisig.import_descriptors_to_bitcoind(
            range=100,
        )
    # Fund the multisig wallet
    with measure_time("fund multisig"):
        bitcoind.fund_addresses(alice_wiring.multisig.change_address)

    logger.info("Rune Bridge setup took %s seconds", time.time() - start)

    yield SimpleNamespace(
        rune_bridge=alice_wiring.bridge,
        rune_bridge_service=alice_wiring.service,
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        root_ord_wallet=root_ord_wallet,
        bridge_ord_multisig=alice_wiring.multisig,
        rune_bridge_contract=rune_bridge_contract,
    )

    logger.info("Restoring EVM snapshot %s", snapshot_id)
    hardhat.revert(snapshot_id)


@pytest.fixture()
def user_ord_wallet(runes_setup) -> OrdWallet:
    return runes_setup.user_ord_wallet


@pytest.fixture()
def root_ord_wallet(runes_setup) -> OrdWallet:
    return runes_setup.root_ord_wallet


@pytest.fixture()
def user_evm_wallet(runes_setup) -> EVMWallet:
    return runes_setup.user_evm_wallet


@pytest.fixture()
def rune_bridge_contract(runes_setup) -> Contract:
    return runes_setup.rune_bridge_contract


@pytest.fixture()
def rune_bridge(runes_setup) -> RuneBridge:
    return runes_setup.rune_bridge


@pytest.fixture()
def rune_bridge_service(runes_setup) -> RuneBridgeService:
    return runes_setup.rune_bridge_service


@pytest.fixture()
def bridge_ord_multisig(runes_setup) -> OrdMultisig:
    return runes_setup.bridge_ord_multisig


@pytest.fixture()
def bridge_util(
    dbsession,
    ord,
    bitcoind,
    hardhat,
    root_ord_wallet,
    rune_bridge,
    rune_bridge_contract,
    rune_bridge_service,
    bridge_ord_multisig,
) -> RuneBridgeUtil:
    return RuneBridgeUtil(
        ord=ord,
        hardhat=hardhat,
        bitcoind=bitcoind,
        dbsession=dbsession,
        root_ord_wallet=root_ord_wallet,
        bridge_ord_multisig=bridge_ord_multisig,
        rune_bridge=rune_bridge,
        rune_bridge_service=rune_bridge_service,
        rune_bridge_contract=rune_bridge_contract,
    )
