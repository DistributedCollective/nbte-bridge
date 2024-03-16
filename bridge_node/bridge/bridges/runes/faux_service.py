# Implement everything rune bridge related here until we have a proper implementation
# TODO: obviously get rid of this module

from web3 import Web3
from web3.types import EventData
import logging
from dataclasses import dataclass
from decimal import Decimal

from eth_utils import to_checksum_address, add_0x_prefix
from anemic.ioc import Container, auto, autowired, service
from bridge.common.btc.rpc import BitcoinRPC
from .evm import load_rune_bridge_abi
from sqlalchemy.orm.session import Session

from ...common.evm.utils import from_wei
from ...common.ord.client import OrdApiClient
from ...common.ord.simple_wallet import SimpleOrdWallet
from ...common.evm.scanner import EvmEventScanner
from ...common.services.key_value_store import KeyValueStore
from ...common.services.transactions import TransactionManager

logger = logging.getLogger(__name__)


@dataclass
class RuneToEvmTransfer:
    evm_address: str
    amount_raw: int
    amount_decimal: Decimal
    txid: str
    vout: int
    rune_name: str


@dataclass
class TokenToBtcTransfer:
    receiver_address: str
    amount_wei: int
    token_address: str
    rune_name: str


@service(scope="global")
class FauxRuneService:
    web3: Web3 = autowired(auto)
    transaction_manager: TransactionManager = autowired(auto)

    bitcoin_rpc_root: BitcoinRPC
    bitcoin_rpc: BitcoinRPC

    ord_api_url = "http://alice-ord"
    bitcoind_host = "bitcoind:18443"
    rune_bridge_contract_address = to_checksum_address("0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9")
    bitcoin_wallet = "alice-ord"

    last_bitcoin_block: str | None = None
    # _evm_addresses_by_deposit_address: dict[str, str]

    def __init__(self, container: Container, *, setting_overrides: dict[str, str] = None):
        if setting_overrides:
            # Hack for testing
            for k, v in setting_overrides.items():
                logger.info("Overriding setting %r with value %r", k, v)
                setattr(self, k, v)

        self.container = container
        self.bitcoin_rpc_root = BitcoinRPC(url=f"http://polaruser:polarpass@{self.bitcoind_host}")
        self.bitcoin_rpc = BitcoinRPC(
            url=f"http://polaruser:polarpass@{self.bitcoind_host}/wallet/{self.bitcoin_wallet}"
        )
        self.rune_bridge_contract = self.web3.eth.contract(
            address=self.rune_bridge_contract_address,
            abi=load_rune_bridge_abi("RuneBridge"),
        )
        self.ord_client = OrdApiClient(
            base_url=self.ord_api_url,
        )
        self.ord_wallet = SimpleOrdWallet(
            bitcoin_rpc=self.bitcoin_rpc,
            ord_client=self.ord_client,
        )

    def _ensure_bitcoin_wallet(self):
        wallets = self.bitcoin_rpc_root.call("listwallets")
        if "alice-ord" not in wallets:
            self.bitcoin_rpc_root.call("createwallet", self.bitcoin_wallet)

    def generate_deposit_address(self, evm_address: str) -> str:
        self._ensure_bitcoin_wallet()

        evm_address = to_checksum_address(evm_address)
        label = f"runes:deposit:{evm_address}"

        # could check existing address here but no need to
        # self.bitcoin_rpc.call("getaddressesbylabel", label)

        return self.bitcoin_rpc.call("getnewaddress", label)

    def scan_rune_deposits(self) -> list[RuneToEvmTransfer]:
        self._ensure_bitcoin_wallet()

        if not self.last_bitcoin_block:
            resp = self.bitcoin_rpc.call("listsinceblock")
        else:
            resp = self.bitcoin_rpc.call("listsinceblock", self.last_bitcoin_block)

        transfers = []
        for tx in resp["transactions"]:
            if tx["category"] != "receive":
                continue
            if "label" not in tx:
                continue
            if not tx["label"].startswith("runes:deposit:"):
                continue
            evm_address = tx["label"][len("runes:deposit:") :]
            txid = tx["txid"]
            vout = tx["vout"]
            outpoint = f"{txid}:{vout}"

            utxos_by_rune = self.ord_client.get("/runes/balances")
            for rune_name, utxos in utxos_by_rune.items():
                if outpoint in utxos:
                    amount_raw = utxos[outpoint]
                    amount_decimal = Decimal(amount_raw) / 10**18
                    break
            else:
                raise ValueError(f"Could not find {outpoint} in {utxos_by_rune}")

            logger.info(
                "Received %s %s for %s at %s:%s", amount_decimal, rune_name, evm_address, txid, vout
            )

            transfer = RuneToEvmTransfer(
                evm_address=evm_address,
                amount_raw=amount_raw,
                amount_decimal=amount_decimal,
                txid=txid,
                vout=vout,
                rune_name=rune_name,
            )
            logger.info("Transfer: %s", transfer)
            transfers.append(transfer)

        self.last_bitcoin_block = resp["lastblock"]
        return transfers

    def send_rune_to_evm(self, transfer: RuneToEvmTransfer):
        logger.info("Executing Rune-to-EVM transfer %s", transfer)
        tx_hash = self.rune_bridge_contract.functions.acceptTransferFromBtc(
            transfer.evm_address,
            transfer.rune_name,
            transfer.amount_raw,
            add_0x_prefix(transfer.txid),
            transfer.vout,
            [],
        ).transact(
            {
                "gas": 10_000_000,
            }
        )
        logger.info("Sent Rune-to-EVM transfer %s, waiting...", tx_hash.hex())
        receipt = self.web3.eth.wait_for_transaction_receipt(
            tx_hash,
            timeout=120,
            poll_latency=2.0,
        )
        assert receipt["status"]
        logger.info("Rune-to-EVM transfer %s confirmed", tx_hash.hex())

    def scan_token_deposits(self) -> list[TokenToBtcTransfer]:
        events: list[TokenToBtcTransfer] = []

        def callback(batch: list[EventData]):
            for event in batch:
                if event["event"] == "RuneTransferToBtc":
                    events.append(
                        TokenToBtcTransfer(
                            receiver_address=event["args"]["receiverBtcAddress"],
                            rune_name=event["args"]["rune"],
                            token_address=event["args"]["token"],
                            amount_wei=event["args"]["amountWei"],
                        )
                    )
                else:
                    logger.warning("Unknown event: %s", event)

        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            key_value_store = tx.find_service(KeyValueStore)
            scanner = EvmEventScanner(
                web3=self.web3,
                events=[
                    self.rune_bridge_contract.events.RuneTransferToBtc,
                ],
                callback=callback,
                dbsession=dbsession,
                block_safety_margin=0,
                key_value_store=key_value_store,
                key_value_store_namespace="runebridge",
                default_start_block=1,
            )
            scanner.scan_new_events()
        return events

    def send_token_to_btc(self, deposit: TokenToBtcTransfer):
        logger.info("Sending to BTC: %s", deposit)
        self._ensure_bitcoin_wallet()
        self.ord_wallet.send_runes(
            rune_name=deposit.rune_name,
            amount=from_wei(deposit.amount_wei),
            receiver_address=deposit.receiver_address,
        )
