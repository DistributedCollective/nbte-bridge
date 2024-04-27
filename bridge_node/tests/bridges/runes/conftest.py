import dataclasses
import logging
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest
from anemic.ioc import (
    Container,
    FactoryRegistry,
)
from eth_typing import ChecksumAddress
from sqlalchemy.orm import (
    Session,
)
from web3.contract import Contract

from bridge.bridges.runes.bridge import RuneBridge
from bridge.bridges.runes.config import (
    RuneBridgeConfig,
    RuneBridgeSecrets,
)
from bridge.bridges.runes.evm import load_rune_bridge_abi
from bridge.bridges.runes.service import RuneBridgeService
from bridge.bridges.runes.wiring import (
    RuneBridgeWiring,
    wire_rune_bridge,
)
from bridge.common.ord.multisig import OrdMultisig
from bridge.common.services.key_value_store import KeyValueStore
from bridge.common.services.transactions import TransactionManager

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
from .bridge_util import RuneBridgeUtil

logger = logging.getLogger(__name__)


MODULE_SETUP_CACHE_KEY = "runes_module_setup"
FEDERATORS = ["alice", "bob", "carol"]


@dataclasses.dataclass
class CachedModuleSetup:
    federator_names: list[str]
    federator_evm_private_keys: list[str]
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
    ord,  # noqa A002
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
            cache.set(MODULE_SETUP_CACHE_KEY, None)  # remove it, so that it's not accidentally used again
            if cached_setup.federator_names != FEDERATORS:
                logger.info("Federators have changed, falling back to re-deploying everything")
                cached_setup = None
            else:
                logger.info(
                    "Found cached setup, attempting to restore snapshot %r",
                    cached_setup.snapshot_id,
                )
                try:
                    hardhat.revert(cached_setup.snapshot_id)
                except Exception:
                    logger.info(
                        "Restoring snapshot %r failed (hardhat probably restarted), "
                        "falling back to re-deploying everything",
                        cached_setup.snapshot_id,
                    )
                    cached_setup = None
                else:
                    logger.info("Restored snapshot successfully")

    if cached_setup:
        logger.info("Reusing cached setup")
        federator_evm_wallets = [
            EVMWallet(
                account=hardhat.web3.eth.account.from_key(evm_private_key),
                name=federator,
            )
            for (federator, evm_private_key) in zip(FEDERATORS, cached_setup.federator_evm_private_keys, strict=False)
        ]
        user_evm_wallet = EVMWallet(
            account=hardhat.web3.eth.account.from_key(cached_setup.user_evm_private_key),
            name="user",
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
            federator_evm_wallets = [
                hardhat.create_test_wallet(federator, impersonate=False) for federator in FEDERATORS
            ]
            user_evm_wallet = hardhat.create_test_wallet("user")

        with measure_time("deploy-access-control"):
            access_control_deployment = hardhat.run_json_command(
                "deploy-access-control",
                "--federators",
                ",".join(evm_wallet.account.address for evm_wallet in federator_evm_wallets),
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
            federator_names=FEDERATORS.copy(),
            federator_evm_private_keys=[wallet.account.key.hex() for wallet in federator_evm_wallets],
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
        federator_evm_wallets=federator_evm_wallets,
        user_evm_wallet=user_evm_wallet,
        rune_bridge_contract=rune_bridge_contract,
        root_ord_wallet=root_ord_wallet,
        user_ord_wallet=user_ord_wallet,
    )


@pytest.fixture()
def runes_setup(
    hardhat: HardhatService,
    bitcoind: BitcoindService,
    ord: OrdService,  # noqa A002
    dbsession,
    dbsession2,
    dbsession3,
    runes_module_setup,
):
    start = time.time()
    snapshot_id = hardhat.snapshot()

    # Use data that's slow to create from the module setup
    root_ord_wallet = runes_module_setup.root_ord_wallet
    user_ord_wallet = runes_module_setup.user_ord_wallet
    federator_evm_wallets = runes_module_setup.federator_evm_wallets
    user_evm_wallet = runes_module_setup.user_evm_wallet
    rune_bridge_contract = runes_module_setup.rune_bridge_contract

    # Fund ord wallets every time
    with measure_time("fund ord wallets"):
        bitcoind.fund_wallets(root_ord_wallet, user_ord_wallet)

    # Multisig wallets

    with measure_time("create multisigs"):
        federator_multisigs = [
            bitcoind.create_test_wallet(
                f"{federator}-runebridge-multisig",
                blank=True,
                disable_private_keys=True,
            )
            for federator in FEDERATORS
        ]

    with measure_time("create keypairs"):
        federator_btc_keypairs = [generate_extended_keypair() for _ in federator_evm_wallets]
        master_xpubs = [pair[1] for pair in federator_btc_keypairs]

    num_required_signers = 2

    # Network
    federator_networks = [
        MockNetwork(node_id=federator_name, leader=(i == 0)) for i, federator_name in enumerate(FEDERATORS)
    ]
    for federator_name, network in zip(FEDERATORS, federator_networks, strict=False):
        network.add_peers(n for n in federator_networks if n.node_id != federator_name)

    federator_dbsessions = [dbsession, dbsession2, dbsession3]

    with measure_time("wiring"):
        federator_wirings = [
            wire_rune_bridge_for_federator(
                rune_bridge_contract_address=rune_bridge_contract.address,
                evm_rpc_url=hardhat.rpc_url,
                btc_rpc_wallet_url=bitcoind.get_wallet_rpc_url(multisig.name),
                btc_num_required_signers=num_required_signers,
                ord_api_url=ord.api_url,
                evm_private_key=evm_wallet.account.key,
                btc_master_xpriv=keypair[0],
                btc_master_xpubs=master_xpubs,
                network=network,
                dbsession=federator_dbsession,
            )
            for federator_dbsession, multisig, evm_wallet, keypair, network in zip(
                federator_dbsessions,
                federator_multisigs,
                federator_evm_wallets,
                federator_btc_keypairs,
                federator_networks,
                strict=False,
            )
        ]

    # Ensure bitcoind sees the wallet
    with measure_time("import descriptors"):
        for wiring in federator_wirings:
            wiring.multisig.import_descriptors_to_bitcoind(
                desc_range=100,
            )

    leader_wiring = federator_wirings[0]
    follower_wirings = federator_wirings[1:]

    # Fund the multisig wallet, only needs to be done once (not for each multisig)
    bitcoind.fund_addresses(leader_wiring.multisig.change_address)

    # Sync ord, hopefully preventing "output in ord but not in bitcoind" errors
    ord.sync_with_bitcoind()

    # Init bridges, necessary for networking
    with measure_time("init bridges"):
        for wiring in federator_wirings:
            wiring.bridge.init()

    logger.info("Rune Bridge setup took %s seconds", time.time() - start)

    yield SimpleNamespace(
        rune_bridge=leader_wiring.bridge,
        rune_bridge_service=leader_wiring.service,
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        root_ord_wallet=root_ord_wallet,
        bridge_ord_multisig=leader_wiring.multisig,
        rune_bridge_contract=rune_bridge_contract,
        federator_wirings=federator_wirings,
        follower_bridges=[w.bridge for w in follower_wirings[1:]],
    )

    logger.info("Restoring EVM snapshot %s", snapshot_id)
    hardhat.revert(snapshot_id)


def wire_rune_bridge_for_federator(
    *,
    dbsession: Session,
    evm_rpc_url: str,
    btc_rpc_wallet_url: str,
    ord_api_url: str,
    rune_bridge_contract_address: ChecksumAddress,
    btc_num_required_signers: int,
    evm_private_key: str | bytes,
    btc_master_xpriv: str | bytes,
    btc_master_xpubs: list[str | bytes],
    network: MockNetwork,
) -> RuneBridgeWiring:
    # TODO: not sure if we should use wire_rune_bridge
    # or directly instantiate it. Directly instantiating is more explicit and suits
    # test, but on the other hand, with wire_rune_bridge we don't have to care
    # about the internals so much, and we're actually testing how it's wired
    # in real life
    transaction_registry = FactoryRegistry("transaction")
    transaction_registry.register(
        interface=KeyValueStore,
        factory=KeyValueStore,
    )
    transaction_registry.register(
        interface=Session,
        factory=lambda _: dbsession,
    )
    alice_transaction_manager = TransactionManager(
        global_container=Container(FactoryRegistry("global")),
        transaction_registry=transaction_registry,
    )
    wiring = wire_rune_bridge(
        config=RuneBridgeConfig(
            bridge_id="test-runebridge",
            rune_bridge_contract_address=rune_bridge_contract_address,
            evm_rpc_url=evm_rpc_url,
            btc_rpc_wallet_url=btc_rpc_wallet_url,
            btc_num_required_signers=btc_num_required_signers,
            ord_api_url=ord_api_url,
            evm_block_safety_margin=0,
            evm_default_start_block=1,
            runes_to_evm_fee_percentage_decimal=Decimal(0),
            btc_network="regtest",
            btc_base_derivation_path="m/13/0/0",
        ),
        secrets=RuneBridgeSecrets(
            evm_private_key=evm_private_key,
            btc_master_xpriv=str(btc_master_xpriv),
            btc_master_xpubs=[str(key) for key in btc_master_xpubs],
        ),
        network=network,
        transaction_manager=alice_transaction_manager,
    )
    wiring.bridge.max_retries = 0  # no retries in tests
    return wiring


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
def follower_bridges(runes_setup) -> list[RuneBridge]:
    return runes_setup.follower_bridges


@pytest.fixture()
def rune_bridge_service(runes_setup) -> RuneBridgeService:
    return runes_setup.rune_bridge_service


@pytest.fixture()
def bridge_ord_multisig(runes_setup) -> OrdMultisig:
    return runes_setup.bridge_ord_multisig


@pytest.fixture()
def bob_service(runes_setup) -> RuneBridgeService:
    return runes_setup.federator_wirings[1].service


@pytest.fixture()
def carol_service(runes_setup) -> RuneBridgeService:
    return runes_setup.federator_wirings[2].service


@pytest.fixture()
def federator_wirings(runes_setup) -> list[RuneBridgeWiring]:
    return runes_setup.federator_wirings


@pytest.fixture()
def bridge_util(
    dbsession,
    ord,  # noqa A002
    bitcoind,
    hardhat,
    root_ord_wallet,
    rune_bridge,
    rune_bridge_contract,
    rune_bridge_service,
    bridge_ord_multisig,
    follower_bridges,
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
        follower_bridges=follower_bridges,
    )
