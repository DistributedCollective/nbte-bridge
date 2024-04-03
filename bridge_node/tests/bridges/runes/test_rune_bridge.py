import logging
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
from web3 import Web3
from web3.contract import Contract

from bridge.bridges.runes.bridge import RuneBridge
from bridge.bridges.runes.config import (
    RuneBridgeConfig,
    RuneBridgeSecrets,
)
from bridge.bridges.runes.evm import load_rune_bridge_abi
from bridge.bridges.runes.service import RuneBridgeService
from bridge.bridges.runes.wiring import wire_rune_bridge
from bridge.common.evm.utils import from_wei
from bridge.common.services.key_value_store import KeyValueStore
from bridge.common.services.transactions import TransactionManager
from ...utils.bitcoin import generate_extended_keypair
from ...mock_network import MockNetwork
from ...services import (
    BitcoindService,
    HardhatService,
    OrdService,
    OrdWallet,
)
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
    bitcoind.fund_wallets(root_ord_wallet, user_ord_wallet)

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
    bridge_multisig_wallet = bitcoind.create_test_wallet(
        "runebridge-multisig",
        blank=True,
        disable_private_keys=True,
    )
    alice_xprv, alice_xpub = generate_extended_keypair()
    bob_xprv, bob_xpub = generate_extended_keypair()

    # TODO: not sure if we should use wire_rune_bridge
    # or directly instantiate it. Directly instantiating is more explicit and suits
    # test, but on the other hand, with wire_rune_bridge we don't have to care
    # about the internals so much, and we're actually testing how it's wired
    # in real life
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
    alice_wiring.multisig.import_descriptors_to_bitcoind(
        range=100,
    )
    # Fund the multisig wallet
    bitcoind.fund_addresses(alice_wiring.multisig.change_address)

    return SimpleNamespace(
        rune_bridge=alice_wiring.bridge,
        rune_bridge_service=alice_wiring.service,
        rune_name=etching.rune,
        user_ord_wallet=user_ord_wallet,
        user_evm_wallet=user_evm_wallet,
        root_ord_wallet=root_ord_wallet,
        rune_bridge_contract=rune_bridge_contract,
        rune_side_token_contract=rune_side_token_contract,
    )


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
def rune_bridge(setup) -> RuneBridge:
    return setup.rune_bridge


@pytest.fixture()
def rune_bridge_service(setup) -> RuneBridgeService:
    return setup.rune_bridge_service


def test_rune_bridge(
    dbsession,
    hardhat,
    ord,
    user_evm_wallet,
    user_ord_wallet,
    root_ord_wallet,
    rune_name,
    rune_bridge_contract,
    rune_side_token_contract,
    rune_bridge,
    rune_bridge_service,
):
    assert user_ord_wallet.get_rune_balance_decimal(rune_name) == 0
    root_ord_wallet.send_runes(
        rune=rune_name,
        amount=1000,
        receiver=user_ord_wallet.get_receiving_address(),
    )
    ord.mine_and_sync()
    assert user_ord_wallet.get_rune_balance_decimal(rune_name) == 1000
    assert (
        rune_side_token_contract.functions.balanceOf(user_evm_wallet.address).call() == 0
    )  # sanity check
    initial_total_supply = rune_side_token_contract.functions.totalSupply().call()

    # Test runes to evm
    with dbsession.begin():
        deposit_address = rune_bridge_service.generate_deposit_address(
            evm_address=user_evm_wallet.address,
            dbsession=dbsession,
        )
    logger.info("DEPOSIT ADDRESS: %s", deposit_address)
    user_ord_wallet.send_runes(
        receiver=deposit_address,
        amount=1000,
        rune=rune_name,
    )
    ord.mine_and_sync()

    rune_bridge.run_iteration()

    hardhat.mine()  # probably not necessary as automining is on

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

    hardhat.mine()  # probably not necessary as automining is on

    receipt = hardhat.web3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt.status

    rune_bridge.run_iteration()

    ord.mine_and_sync()

    user_rune_balance = user_ord_wallet.get_rune_balance_decimal(rune_name)
    assert user_rune_balance == 1000
