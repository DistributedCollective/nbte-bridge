import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import eth_utils
from sqlalchemy.orm import (
    Session,
)
from web3 import Web3
from web3.contract import Contract
from web3.types import EventData

from bridge.common.btc.rpc import BitcoinRPC
from .models import User, DepositAddress
from ...common.evm.scanner import EvmEventScanner
from ...common.ord.client import OrdApiClient
from ...common.ord.multisig import OrdMultisig, RuneTransfer
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
        ord_multisig: OrdMultisig,
        web3: Web3,
        rune_bridge_contract: Contract,
    ):
        self.config = config
        self.bitcoin_rpc = bitcoin_rpc
        self.rune_bridge_contract = rune_bridge_contract
        self.ord_client = ord_client
        self.ord_multisig = ord_multisig
        self.transaction_manager = transaction_manager
        self.web3 = web3

    def generate_deposit_address(self, *, evm_address: str, dbsession: Session) -> str:
        # TODO: dbsession now passed as parameter, seems ugly?
        if not eth_utils.is_checksum_formatted_address(evm_address):
            raise ValueError(
                f"Invalid EVM address: {evm_address} (not a valid address or not checksummed properly)"
            )

        user = (
            dbsession.query(User)
            .filter_by(bridge_id=self.config.bridge_id, evm_address=evm_address)
            .first()
        )
        if not user:
            user = User(
                bridge_id=self.config.bridge_id,
                evm_address=evm_address,
            )
            dbsession.add(user)
            dbsession.flush()

        deposit_address = user.deposit_address
        if not deposit_address:
            deposit_address = DepositAddress(
                user_id=user.id,
                btc_address=self.ord_multisig.derive_address(user.id),
            )
            dbsession.add(deposit_address)
            dbsession.flush()

        return deposit_address.btc_address

    def scan_rune_deposits(self) -> list[RuneToEvmTransfer]:
        last_block_key = f"{self.config.bridge_id}:btc:deposits:last_scanned_block"
        with self.transaction_manager.transaction() as tx:
            key_value_store = tx.find_service(KeyValueStore)
            last_bitcoin_block = key_value_store.get_value(last_block_key, default_value=None)

        if not last_bitcoin_block:
            logger.info("Scanning Rune deposits from the beginning")
            resp = self.bitcoin_rpc.call("listsinceblock")
        else:
            logger.info("Scanning Rune deposits from block %s", last_bitcoin_block)
            resp = self.bitcoin_rpc.call("listsinceblock", last_bitcoin_block)

        transfers = []
        for tx in resp["transactions"]:
            if tx["category"] != "receive":
                continue

            btc_address = tx.get("address")
            if not btc_address:
                logger.warning("No BTC address in transaction %s", tx)
                continue

            if btc_address == self.ord_multisig.change_address:
                logger.info("Ignoring tx to change address %s", btc_address)
                continue

            # TODO: temporary solution here, we should actually always store RuneDeposits
            with self.transaction_manager.transaction() as _tx:
                dbsession = _tx.find_service(Session)
                deposit_address = (
                    dbsession.query(DepositAddress).filter_by(btc_address=btc_address).first()
                )
                if not deposit_address:
                    logger.warning("No deposit address found for %s", tx)
                    continue
                evm_address = deposit_address.user.evm_address

            txid = tx["txid"]
            vout = tx["vout"]

            output = self.ord_client.get_output(txid, vout)
            logger.info(
                "Received %s runes in outpoint %s:%s (user %s)",
                len(output["runes"]),
                txid,
                vout,
                evm_address,
            )
            for rune_name, balance_entry in output["runes"]:
                amount_raw = balance_entry["amount"]
                amount_decimal = Decimal(amount_raw) / 10 ** balance_entry["divisibility"]
                logger.info(
                    "Received %s %s for %s at %s:%s",
                    amount_decimal,
                    rune_name,
                    evm_address,
                    txid,
                    vout,
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
            eth_utils.add_0x_prefix(transfer.txid),
            transfer.vout,
            [],
        ).transact(
            {
                "gas": 500_000,
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
        # TODO: multisig transfers
        self.ord_multisig.send_runes(
            transfers=[
                RuneTransfer(
                    rune=deposit.rune_name,
                    receiver=deposit.receiver_address,
                    # TODO: handle divisibility etc, it might not always be the same as wei
                    amount=deposit.amount_wei,
                )
            ]
        )
