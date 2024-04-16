import functools
import logging
import time
from decimal import Decimal
from typing import (
    Protocol,
)

import pyord
import eth_utils
from eth_account.account import LocalAccount
from eth_account.messages import encode_defunct
import sqlalchemy as sa
from sqlalchemy.orm import (
    Session,
)
from web3 import Web3
from web3.contract import Contract
from web3.types import EventData

from bridge.common.btc.rpc import BitcoinRPC
from .models import User, DepositAddress
from ...common.evm.scanner import EvmEventScanner
from ...common.evm.utils import to_wei
from ...common.models.key_value_store import KeyValuePair
from ...common.ord.client import OrdApiClient
from ...common.ord.multisig import OrdMultisig, RuneTransfer
from ...common.services.key_value_store import KeyValueStore
from ...common.services.transactions import TransactionManager
from . import messages

logger = logging.getLogger(__name__)


class RuneBridgeServiceConfig(Protocol):
    bridge_id: str
    evm_block_safety_margin: int
    evm_default_start_block: int
    runes_to_evm_fee_percentage_decimal: Decimal


class RuneBridgeService:
    def __init__(
        self,
        *,
        config: RuneBridgeServiceConfig,
        transaction_manager: TransactionManager,
        bitcoin_rpc: BitcoinRPC,
        ord_client: OrdApiClient,
        ord_multisig: OrdMultisig,
        evm_account: LocalAccount,
        web3: Web3,
        rune_bridge_contract: Contract,
    ):
        self.config = config
        self.bitcoin_rpc = bitcoin_rpc
        self.rune_bridge_contract = rune_bridge_contract
        self.ord_client = ord_client
        self.ord_multisig = ord_multisig
        self.transaction_manager = transaction_manager
        self.evm_account = evm_account
        self.web3 = web3

    def generate_deposit_address(self, *, evm_address: str, dbsession: Session) -> str:
        # TODO: dbsession now passed as parameter, seems ugly?
        try:
            evm_address = eth_utils.to_checksum_address(evm_address)
        except Exception as e:
            raise ValueError(f"Invalid EVM address: {evm_address}") from e

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

    def scan_rune_deposits(self) -> list[messages.RuneToEvmTransfer]:
        last_block_key = f"{self.config.bridge_id}:btc:deposits:last_scanned_block"
        with self.transaction_manager.transaction() as tx:
            key_value_store = tx.find_service(KeyValueStore)
            last_bitcoin_block = key_value_store.get_value(last_block_key, default_value=None)

        required_confirmations = 1
        if not last_bitcoin_block:
            logger.info("Scanning Rune deposits from the beginning")
            resp = self.bitcoin_rpc.call("listsinceblock", "", required_confirmations)
        else:
            logger.info("Scanning Rune deposits from block %s", last_bitcoin_block)
            resp = self.bitcoin_rpc.call(
                "listsinceblock", last_bitcoin_block, required_confirmations
            )

        # Sync with Bitcoind to avoid missing rune outputs
        self._sync_ord_with_bitcoind()

        # New last block will be stored in the DB
        new_last_block = resp["lastblock"]

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

            tx_confirmations = tx["confirmations"]
            txid = tx["txid"]
            vout = tx["vout"]

            logger.info(
                "found transfer: %s:%s, user %s with %s confirmations",
                txid,
                vout,
                evm_address,
                tx_confirmations,
            )

            if tx_confirmations < required_confirmations:
                # Zero-confirmation txs will be scanned automatically next time
                continue

            output = self.ord_client.get_output(txid, vout)
            logger.info(
                "Received %s runes in outpoint %s:%s (user %s)",
                len(output["runes"]),
                txid,
                vout,
                evm_address,
            )

            if not output["runes"]:
                # TODO: store these too
                logger.warning("Transfer without runes: %s:%s", txid, vout)
                continue

            for rune_name, balance_entry in output["runes"]:
                # TODO: validate postage, but still store in DB
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

                transfer = messages.RuneToEvmTransfer(
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
            key_value_store.set_value(last_block_key, new_last_block)
        return transfers

    def _sync_ord_with_bitcoind(self, timeout=60, poll_interval=1):
        start = time.time()
        bitcoind_block_count = self.bitcoin_rpc.call("getblockcount")
        while time.time() - start < timeout:
            ord_block_count = self.ord_client.get("/blockcount")
            if ord_block_count >= bitcoind_block_count:
                break
            logger.info(
                "Waiting for ord to sync to block %d (current: %d)",
                bitcoind_block_count,
                ord_block_count,
            )
            time.sleep(poll_interval)
        else:
            raise TimeoutError("ORD did not sync in time")

    def get_last_scanned_bitcoin_block(self, dbsession: Session) -> str | None:
        # TODO: temporary code, remove
        last_block_key = f"{self.config.bridge_id}:btc:deposits:last_scanned_block"
        val = dbsession.query(KeyValuePair).filter_by(key=last_block_key).one_or_none()
        return val.value if val else None

    def get_pending_deposits_for_evm_address(
        self,
        evm_address: str,
        last_block: int,
        dbsession: Session,
    ) -> list[dict]:
        # TODO: temporary code, remove
        evm_address = eth_utils.to_checksum_address(evm_address)
        logger.debug("Getting transactions for %s since %s", evm_address, last_block)
        user = (
            dbsession.query(User)
            .filter_by(
                evm_address=evm_address,
                bridge_id=self.config.bridge_id,
            )
            .one_or_none()
        )
        if not user:
            logger.debug("No user found for %s", evm_address)
            return []
        deposit_address = user.deposit_address
        if not deposit_address:
            logger.debug("No deposit address found for %s", evm_address)
            return []

        @functools.lru_cache
        def get_rune_symbol(rune):
            resp = self.ord_client.get_rune(rune)
            if not resp:
                return ""
            return resp["entry"]["symbol"]

        logger.debug("User %s has deposit address %s", evm_address, deposit_address.btc_address)
        resp = self.bitcoin_rpc.call("listsinceblock", last_block)
        deposits = []
        logger.debug(
            "Got %s transactions since requested block (for all users)", len(resp["transactions"])
        )
        for tx in resp["transactions"]:
            if tx["category"] != "receive":
                continue
            if "address" not in tx:
                continue
            if tx["address"] != deposit_address.btc_address:
                continue
            logger.debug("Found tx: %s", tx)
            txid = tx["txid"]
            vout = tx["vout"]
            output = self.ord_client.get_output(txid, vout)
            logger.debug("Received %s runes in outpoint %s:%s", len(output["runes"]), txid, vout)
            if not output["runes"]:
                # Temporary solution to show something immediately
                # Ord only shows outputs if they are indexed properly
                deposits.append(
                    {
                        "btc_deposit_txid": txid,
                        "btc_deposit_vout": vout,
                        "rune_name": "",
                        "rune_symbol": "",
                        "amount_decimal": "0",
                        "fee_amount_decimal": "0",
                        "receive_amount_decimal": "0",
                        "status": "detected",
                        "evm_transfer_tx_hash": None,
                    }
                )
            for rune_name, balance_entry in output["runes"]:
                amount_raw = balance_entry["amount"]
                amount_decimal = Decimal(amount_raw) / 10 ** balance_entry["divisibility"]
                fee_decimal = amount_decimal * self.config.runes_to_evm_fee_percentage_decimal / 100
                receive_amount_decimal = amount_decimal - fee_decimal
                transfer = messages.RuneToEvmTransfer(
                    evm_address=evm_address,
                    amount_raw=amount_raw,
                    amount_decimal=amount_decimal,
                    txid=txid,
                    vout=vout,
                    rune_name=rune_name,
                )
                data = self._read_rune_to_evm_transfer_key_value_store_data(
                    transfer,
                    dbsession=dbsession,
                )
                deposits.append(
                    {
                        "btc_deposit_txid": txid,
                        "btc_deposit_vout": vout,
                        "rune_name": rune_name,
                        "rune_symbol": get_rune_symbol(rune_name),
                        "amount_decimal": str(amount_decimal),
                        "fee_decimal": str(fee_decimal),
                        "receive_amount_decimal": str(receive_amount_decimal),
                        "status": data.get("status", "seen"),
                        "evm_transfer_tx_hash": data.get("transfer_tx_hash", None),
                    }
                )
        return deposits

    def send_rune_to_evm(self, transfer: messages.RuneToEvmTransfer, signatures: list[str]):
        logger.info("Executing Rune-to-EVM transfer %s", transfer)
        rune = pyord.Rune.from_str(transfer.rune_name)
        tx_hash = self.rune_bridge_contract.functions.acceptTransferFromBtc(
            transfer.evm_address,
            rune.n,
            transfer.amount_raw,
            eth_utils.add_0x_prefix(transfer.txid),
            transfer.vout,
            signatures,
        ).transact(
            {
                "gas": 500_000,
            }
        )
        logger.info("Sent Rune-to-EVM transfer %s, waiting...", tx_hash.hex())

        # TODO: temporary code, remove
        self._update_rune_to_evm_transfer_key_value_store_data(
            transfer,
            {
                "status": "sent_to_evm",
                "transfer_tx_hash": tx_hash.hex(),
            },
        )

        receipt = self.web3.eth.wait_for_transaction_receipt(
            tx_hash,
            timeout=120,
            poll_latency=2.0,
        )
        self._update_rune_to_evm_transfer_key_value_store_data(
            transfer,
            {
                "status": "confirmed",
            },
        )
        assert receipt["status"]
        logger.info("Rune-to-EVM transfer %s confirmed", tx_hash.hex())

    def answer_sign_rune_to_evm_transfer_question(
        self,
        message: messages.SignRuneToEvmTransferQuestion,
    ) -> messages.SignRuneToEvmTransferAnswer:
        transfer = message.transfer
        rune = self.ord_client.get_rune(transfer.rune_name)
        if not rune:
            raise ValueError(f"Rune {transfer.rune_name} not found (transfer {transfer})")

        # TODO: rather validate by reading from the DB
        rune_response = self.ord_client.get_rune(transfer.rune_name)
        if not rune_response:
            raise ValueError(f"Rune {transfer.rune_name} not found")
        divisibility = rune_response["entry"]["divisibility"]
        if transfer.amount_decimal != Decimal(transfer.amount_raw) / (10**divisibility):
            raise ValueError(
                f"Amount mismatch: {transfer.amount_decimal!r} != {transfer.amount_raw} / 10^{divisibility}"
            )

        balance_at_output = self.ord_multisig.get_rune_balance_at_output(
            txid=transfer.txid,
            vout=transfer.vout,
            rune_name=transfer.rune_name,
        )
        if balance_at_output != transfer.amount_raw:
            raise ValueError(
                f"Balance at output {transfer.txid}:{transfer.vout} is {balance_at_output}, "
                f"expected {transfer.amount_raw}"
            )

        # TODO: validate the deposit address
        # user = self.get_user_by_deposit_address(deposit_address=transfer.evm_address)
        # if not user:
        #     raise ValueError(f"User not found for deposit address {transfer.evm_address}")
        # if not user.evm_address == transfer.evm_address:
        #     raise ValueError(f"User EVM address mismatch: {user.evm_address} != {transfer.evm_address}")

        rune = pyord.Rune.from_str(transfer.rune_name)
        message_hash = self.rune_bridge_contract.functions.getAcceptTransferFromBtcMessageHash(
            transfer.evm_address,
            rune.n,
            to_wei(transfer.amount_decimal),
            eth_utils.add_0x_prefix(transfer.txid),
            transfer.vout,
        ).call()
        signable_message = encode_defunct(primitive=message_hash)
        signed_message = self.evm_account.sign_message(signable_message)
        return messages.SignRuneToEvmTransferAnswer(
            signature=signed_message.signature.hex(),
            signer=self.evm_account.address,
        )

    def answer_sign_rune_token_to_btc_transfer_question(
        self,
        message: messages.SignRuneTokenToBtcTransferQuestion,
    ) -> messages.SignRuneTokenToBtcTransferAnswer:
        unsigned_psbt = self.ord_multisig.deserialize_psbt(message.unsigned_psbt_serialized)
        # TODO: validation
        signed_psbt = self.ord_multisig.sign_psbt(unsigned_psbt)
        return messages.SignRuneTokenToBtcTransferAnswer(
            signed_psbt_serialized=self.ord_multisig.serialize_psbt(signed_psbt),
            signer_xpub=self.ord_multisig.signer_xpub,
        )

    def _get_rune_to_evm_transfer_key_value_store_key(
        self, transfer: messages.RuneToEvmTransfer
    ) -> str:
        return f"{self.config.bridge_id}:rune-to-evm-transfer:{transfer.txid}:{transfer.vout}:{transfer.rune_name}"

    def _update_rune_to_evm_transfer_key_value_store_data(
        self,
        transfer: messages.RuneToEvmTransfer,
        data: dict,
    ):
        with self.transaction_manager.transaction() as tx:
            key = self._get_rune_to_evm_transfer_key_value_store_key(transfer)
            key_value_store = tx.find_service(KeyValueStore)
            existing_data = (
                key_value_store.get_value(
                    key,
                    default_value={},
                )
                or {}
            )
            existing_data.update(data)
            key_value_store.set_value(
                key,
                existing_data,
            )

    def _read_rune_to_evm_transfer_key_value_store_data(
        self, transfer: messages.RuneToEvmTransfer, dbsession: Session
    ):
        val = (
            dbsession.query(KeyValuePair)
            .filter_by(
                key=self._get_rune_to_evm_transfer_key_value_store_key(transfer),
            )
            .one_or_none()
        )
        if val:
            val = val.value
        if not val:
            return {}
        return val

    def scan_rune_token_deposits(self) -> list[messages.RuneTokenToBtcTransfer]:
        events: list[messages.RuneTokenToBtcTransfer] = []

        def callback(batch: list[EventData]):
            for event in batch:
                if event["event"] == "RuneTransferToBtc":
                    events.append(
                        messages.RuneTokenToBtcTransfer(
                            receiver_address=event["args"]["receiverBtcAddress"],
                            rune_name=event["args"]["rune"],
                            token_address=event["args"]["token"],
                            net_rune_amount=event["args"]["netRuneAmount"],
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

    def send_rune_token_to_btc(self, deposit: messages.RuneTokenToBtcTransfer):
        logger.info("Sending to BTC: %s", deposit)
        # TODO: multisig transfers
        self.ord_multisig.send_runes(
            transfers=[
                RuneTransfer(
                    rune=deposit.rune_name,
                    receiver=deposit.receiver_address,
                    # TODO: handle divisibility etc, it might not always be the same as wei
                    amount=deposit.net_rune_amount,
                )
            ]
        )

    def get_user_by_deposit_address(self, deposit_address: str) -> User | None:
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            obj = dbsession.scalars(
                sa.select(DepositAddress)
                .join(User)
                .filter(
                    User.bridge_id == self.config.bridge_id,
                    DepositAddress.btc_address == deposit_address,
                )
            ).one_or_none()
            if not obj:
                return None
            return obj.user

    def get_runes_to_evm_num_required_signers(self) -> int:
        return self.rune_bridge_contract.functions.numRequiredFederators().call()

    def get_evm_to_runes_num_required_signers(self) -> int:
        return self.ord_multisig.num_required_signers
