import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from eth_utils import (
    add_0x_prefix,
    to_checksum_address,
)
from sqlalchemy.orm import (
    Session,
)
from web3 import Web3
from web3.contract import Contract
from web3.types import EventData

from bridge.common.btc.rpc import BitcoinRPC
from ...common.evm.scanner import EvmEventScanner
from ...common.evm.utils import from_wei
from ...common.ord.client import OrdApiClient
from ...common.ord.simple_wallet import SimpleOrdWallet
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


class RuneBridgeServiceConfig(Protocol):
    bridge_id: str
    evm_block_safety_margin: int
    evm_default_start_block: int


class RuneBridgeService:
    def __init__(
        self,
        *,
        config: RuneBridgeServiceConfig,
        transaction_manager: TransactionManager,
        bitcoin_rpc: BitcoinRPC,
        ord_client: OrdApiClient,
        ord_wallet: SimpleOrdWallet,
        web3: Web3,
        rune_bridge_contract: Contract,
    ):
        self.config = config
        self.bitcoin_rpc = bitcoin_rpc
        self.rune_bridge_contract = rune_bridge_contract
        self.ord_client = ord_client
        self.ord_wallet = ord_wallet
        self.transaction_manager = transaction_manager
        self.web3 = web3

    def generate_deposit_address(self, evm_address: str) -> str:
        evm_address = to_checksum_address(evm_address)
        label = f"runes:deposit:{evm_address}"

        # could check existing address here but no need to
        # self.bitcoin_rpc.call("getaddressesbylabel", label)

        return self.bitcoin_rpc.call("getnewaddress", label)

    def scan_rune_deposits(self) -> list[RuneToEvmTransfer]:
        last_block_key = f"{self.config.bridge_id}:btc:deposits:last_scanned_block"
        with self.transaction_manager.transaction() as tx:
            key_value_store = tx.find_service(KeyValueStore)
            last_bitcoin_block = key_value_store.get_value(last_block_key, default_value=None)

        if not last_bitcoin_block:
            resp = self.bitcoin_rpc.call("listsinceblock")
        else:
            resp = self.bitcoin_rpc.call("listsinceblock", last_bitcoin_block)

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

        with self.transaction_manager.transaction() as tx:
            key_value_store = tx.find_service(KeyValueStore)
            key_value_store.set_value(last_block_key, resp["lastblock"])
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
                block_safety_margin=self.config.evm_block_safety_margin,
                key_value_store=key_value_store,
                key_value_store_namespace=self.config.bridge_id,
                default_start_block=self.config.evm_default_start_block,
            )
            scanner.scan_new_events()
        return events

    def send_token_to_btc(self, deposit: TokenToBtcTransfer):
        logger.info("Sending to BTC: %s", deposit)
        self.ord_wallet.send_runes(
            rune_name=deposit.rune_name,
            amount=from_wei(deposit.amount_wei),
            receiver_address=deposit.receiver_address,
        )
