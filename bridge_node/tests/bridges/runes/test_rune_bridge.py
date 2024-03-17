import logging
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker, Session

from bridge.bridges.runes.bridge import RuneBridge
from bridge.bridges.runes.faux_service import FauxRuneService
from bridge.common.evm.account import Account
from bridge.common.p2p.network import Network
from bridge.common.services.key_value_store import KeyValueStore

import pytest
from web3 import Web3
from web3.contract import Contract

from bridge.bridges.runes.evm import load_rune_bridge_abi
from anemic.ioc import FactoryRegistrySet, Container
from bridge.common.services.transactions import register_transaction_manager
from bridge.common.evm.utils import from_wei
from ...mock_network import MockNetwork
from ...services import BitcoindService, HardhatService, OrdService, OrdWallet
from ...services.hardhat import EVMWallet

logger = logging.getLogger(__name__)


@pytest.fixture()
def setup(
    hardhat: HardhatService,
    bitcoind: BitcoindService,
    ord: OrdService,
    dbengine,
):
    root_ord_wallet = ord.create_test_wallet("root-ord")  # used for funding other wallets
    user_ord_wallet = ord.create_test_wallet("user-ord")  # used by the "end user"
    alice_btc_wallet = bitcoind.create_test_wallet("alice-bridge")  # used by the bridge backend
    bitcoind.fund_wallets(root_ord_wallet, alice_btc_wallet, user_ord_wallet)

    etching = root_ord_wallet.etch_test_rune("RUNETEST")
    bitcoind.mine()

    alice_evm_wallet = hardhat.create_test_wallet("alice", impersonate=False)
    user_evm_wallet = hardhat.create_test_wallet("user")

    deployment = hardhat.run_json_command(
        "runes-deploy-regtest",
        "--rune-name",
        etching.rune,
        "--owner",
        alice_evm_wallet.address,
    )

    rune_bridge_contract = hardhat.web3.eth.contract(
        address=deployment["addresses"]["RuneBridge"],
        abi=load_rune_bridge_abi("RuneBridge"),
    )

    rune_side_token_contract = hardhat.web3.eth.contract(
        address=rune_bridge_contract.functions.getTokenByRune(etching.rune).call(),
        abi=load_rune_bridge_abi("RuneSideToken"),
    )

    # NETWORK

    alice_network = MockNetwork(node_id="alice", leader=True)
    bob_network = MockNetwork(node_id="bob")
    carol_network = MockNetwork(node_id="carol")

    alice_network.add_peers([bob_network, carol_network])
    bob_network.add_peers([alice_network, carol_network])
    carol_network.add_peers([alice_network, bob_network])

    alice_container = create_global_container(
        network=alice_network,
        evm_account=alice_evm_wallet.account,
        web3=alice_evm_wallet.web3,
        dbengine=dbengine,
        rune_bridge_contract_address=rune_bridge_contract.address,
        bitcoin_wallet_name=alice_btc_wallet.name,
    )
    return SimpleNamespace(
        global_container=alice_container,
        rune_name=etching.rune,
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        root_ord_wallet=root_ord_wallet,
        rune_bridge_contract=rune_bridge_contract,
        rune_side_token_contract=rune_side_token_contract,
    )


def create_global_container(
    network: Network,
    evm_account,
    web3,
    dbengine,
    rune_bridge_contract_address,
    bitcoin_wallet_name,
):
    registries = FactoryRegistrySet()
    global_registry = registries.create_registry("global")
    transaction_registry = registries.create_registry("transaction")

    global_registry.register_singleton(
        interface=Network,
        singleton=network,
    )

    global_registry.register_singleton(
        interface=Account,
        singleton=evm_account,
    )

    global_registry.register_singleton(
        interface=Web3,
        singleton=web3,
    )

    def rune_service_factory(container):
        # TODO: just hack this now so we'll get forwards
        return FauxRuneService(
            container,
            setting_overrides={
                "ord_api_url": "http://localhost:3080",
                "bitcoind_host": "localhost:18443",
                "rune_bridge_contract_address": rune_bridge_contract_address,
                "bitcoin_wallet": bitcoin_wallet_name,
            },
        )

    global_registry.register(
        interface=FauxRuneService,
        factory=rune_service_factory,
    )

    global_registry.register(
        interface=RuneBridge,
        factory=RuneBridge,
    )

    register_transaction_manager(
        global_registry=global_registry,
        transaction_registry=transaction_registry,
    )

    transaction_registry.register(
        interface=KeyValueStore,
        factory=KeyValueStore,
    )

    session_factory = sessionmaker(bind=dbengine)

    transaction_registry.register(
        interface=Session,
        factory=lambda _: session_factory(),
    )

    return Container(global_registry)


@pytest.fixture()
def global_container(setup) -> Container:
    return setup.global_container


@pytest.fixture()
def rune_name(setup) -> str:
    return setup.rune_name


@pytest.fixture()
def user_ord_wallet(setup) -> OrdWallet:
    return setup.user_ord_wallet


@pytest.fixture()
def root_ord_wallet(setup) -> OrdWallet:
    return setup.root_ord_wallet


@pytest.fixture()
def user_evm_wallet(setup) -> EVMWallet:
    return setup.user_evm_wallet


@pytest.fixture()
def rune_bridge_contract(setup) -> Contract:
    return setup.rune_bridge_contract


@pytest.fixture()
def rune_side_token_contract(setup) -> Contract:
    return setup.rune_side_token_contract


@pytest.fixture()
def rune_bridge(global_container):
    return global_container.get(interface=RuneBridge)


@pytest.fixture()
def rune_bridge_service(global_container):
    return global_container.get(interface=FauxRuneService)


def test_rune_bridge(
    bitcoind,
    hardhat,
    user_evm_wallet,
    user_ord_wallet,
    root_ord_wallet,
    rune_name,
    rune_bridge_contract,
    rune_side_token_contract,
    rune_bridge,
    rune_bridge_service,
):
    assert user_ord_wallet.get_rune_balance(rune_name) == 0
    root_ord_wallet.send_runes(
        rune=rune_name,
        amount=1000,
        receiver=user_ord_wallet.get_receiving_address(),
    )
    bitcoind.mine()
    assert user_ord_wallet.get_rune_balance(rune_name) == 1000
    assert (
        rune_side_token_contract.functions.balanceOf(user_evm_wallet.address).call() == 0
    )  # sanity check
    initial_total_supply = rune_side_token_contract.functions.totalSupply().call()

    # Test runes to evm
    deposit_address = rune_bridge_service.generate_deposit_address(
        evm_address=user_evm_wallet.address,
    )
    logger.info("DEPOSIT ADDRESS: %s", deposit_address)
    user_ord_wallet.send_runes(
        receiver=deposit_address,
        amount=1000,
        rune=rune_name,
    )
    bitcoind.mine()

    rune_bridge.run_iteration()

    hardhat.mine()

    user_evm_token_balance = rune_side_token_contract.functions.balanceOf(
        user_evm_wallet.address
    ).call()

    assert from_wei(user_evm_token_balance) == 1000
    assert (
        from_wei(rune_side_token_contract.functions.totalSupply().call() - initial_total_supply)
        == 1000
    )

    user_btc_address = user_ord_wallet.get_new_address()

    logger.info("TRANSFERRING TOKENS")
    tx_hash = rune_bridge_contract.functions.transferToBtc(
        rune_side_token_contract.address,
        Web3.to_wei(1000, "ether"),
        user_btc_address,
    ).transact(
        {
            "gas": 10_000_000,
            "from": user_evm_wallet.address,
        }
    )

    hardhat.mine()
    receipt = hardhat.web3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt.status

    rune_bridge.run_iteration()
    bitcoind.rpc.mine_blocks(2)

    user_rune_balance = user_ord_wallet.get_rune_balance(rune_name)
    assert user_rune_balance == 1000
