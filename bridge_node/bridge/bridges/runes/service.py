import dataclasses
import functools
import logging
import time
from decimal import Decimal
from typing import (
    Callable,
    Protocol,
)

import eth_utils
import pyord
import sqlalchemy as sa
from eth_account.account import LocalAccount
from eth_account.messages import encode_defunct
from hexbytes import HexBytes
from sqlalchemy.orm import (
    Session,
)
from web3 import Web3
from web3.contract import Contract
from web3.types import EventData
from web3.exceptions import (
    TransactionIndexingInProgress,
    TransactionNotFound,
)

from bridge.common.btc.fees import BitcoinFeeEstimator
from bridge.common.btc.rpc import BitcoinRPC
from . import messages
from .evm import load_rune_bridge_abi
from .models import (
    Bridge,
    DepositAddress,
    IncomingBtcTx,
    IncomingBtcTxStatus,
    Rune,
    RuneDeposit,
    RuneDepositStatus,
    RuneTokenDeposit,
    RuneTokenDepositStatus,
    User,
)
from ...common.btc.types import BitcoinNetwork
from ...common.evm.scanner import EvmEventScanner
from ...common.evm.utils import recover_message
from ...common.models.key_value_store import KeyValuePair
from ...common.ord.client import OrdApiClient
from ...common.ord.multisig import (
    OrdMultisig,
    RuneTransfer,
)
from ...common.ord.types import (
    rune_from_str,
)
from ...common.services.key_value_store import KeyValueStore
from ...common.services.transactions import TransactionManager

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TransferAmounts:
    amount_decimal: Decimal
    amount_raw: int
    fee_decimal: Decimal
    fee_raw: int
    net_amount_decimal: Decimal
    net_amount_raw: int


class ValidationError(ValueError):
    pass


class RuneBridgeServiceConfig(Protocol):
    bridge_id: str
    evm_block_safety_margin: int
    evm_default_start_block: int
    runes_to_evm_fee_percentage_decimal: Decimal
    btc_min_confirmations: int
    btc_min_postage_sat: int
    btc_listsinceblock_buffer: int
    btc_network: BitcoinNetwork


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
        self._bridge_id = None
        self._btc_fee_estimator = BitcoinFeeEstimator(
            rpc=bitcoin_rpc,
            network=config.btc_network,
        )

        self._get_block_time_by_hash = functools.lru_cache(256)(self._get_block_time_by_hash)

    def init(self):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            bridge = dbsession.query(Bridge).filter_by(name=self.bridge_name).one_or_none()
            if not bridge:
                bridge = Bridge(name=self.config.bridge_id)
                dbsession.add(bridge)
                dbsession.flush()
            self._bridge_id = bridge.id

    @property
    def bridge_id(self) -> int:
        if self._bridge_id is None:
            raise ValueError("Bridge ID not set - service is not initialized")
        return self._bridge_id

    @property
    def bridge_name(self) -> str:
        return self.config.bridge_id

    def generate_deposit_address(self, *, evm_address: str, dbsession: Session) -> str:
        # TODO: dbsession now passed as parameter, seems ugly?
        try:
            evm_address = eth_utils.to_checksum_address(evm_address)
        except Exception as e:
            raise ValueError(f"Invalid EVM address: {evm_address}") from e

        user = (
            dbsession.query(User)
            .filter_by(bridge_id=self.bridge_id, evm_address=evm_address)
            .first()
        )
        if not user:
            user = User(
                bridge_id=self.bridge_id,
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

    def scan_rune_deposits(self):
        last_block_key = f"{self.bridge_name}:btc:deposits:last_scanned_block"
        with self.transaction_manager.transaction() as tx:
            key_value_store = tx.find_service(KeyValueStore)
            last_bitcoin_block = key_value_store.get_value(last_block_key, default_value=None)

        required_confirmations = self.config.btc_min_confirmations
        listsinceblock_buffer = self.config.btc_listsinceblock_buffer
        if listsinceblock_buffer < required_confirmations:
            raise ValueError(
                f"listsinceblock_buffer ({listsinceblock_buffer}) must be >= required_confirmations ({required_confirmations})"
            )

        if not last_bitcoin_block:
            logger.info("Scanning Rune deposits from the beginning")
            resp = self.bitcoin_rpc.call("listsinceblock", "", listsinceblock_buffer)
        else:
            logger.info("Scanning Rune deposits from block %s", last_bitcoin_block)
            resp = self.bitcoin_rpc.call(
                "listsinceblock",
                last_bitcoin_block,
                listsinceblock_buffer,
            )

        # Sync with Bitcoind to avoid missing rune outputs
        self._sync_ord_with_bitcoind()

        # New last block will be stored in the DB
        new_last_block = resp["lastblock"]
        logger.info("New last block: %s", new_last_block)

        # Filter invalid transactions and map ord_output outside of db transaction
        # Also keep track of newly seen runes
        rune_names = set()
        transactions = []
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

            txid = tx["txid"]
            vout = tx["vout"]
            tx_confirmations = tx["confirmations"]
            ord_output = tx["ord_output"] = None
            if tx_confirmations > 0:
                # TXs without confirmations are not indexed by ord
                for _ in range(10):
                    ord_output = self.ord_client.get_output(txid, vout)
                    if ord_output["indexed"]:
                        tx["ord_output"] = ord_output
                        break
                    logger.info("Output %s:%s not indexed in ord yet, waiting", txid, vout)
                    self._sleep()
                else:
                    raise RuntimeError("Output not indexed in ord after 10 tries")

            if ord_output:
                for spaced_rune_name, _ in ord_output["runes"]:
                    rune_names.add(spaced_rune_name)

            transactions.append(tx)

        rune_entries = []
        for rune_name in rune_names:
            rune_response = self.ord_client.get_rune(rune_name)
            if not rune_response:
                raise RuntimeError(f"Rune {rune_name} not found in ord")
            rune_entries.append(rune_response["entry"])

        num_transfers = 0
        with self.transaction_manager.transaction() as _tx:
            dbsession = _tx.find_service(Session)
            key_value_store = _tx.find_service(KeyValueStore)

            logger.info("Indexing %s runes", len(rune_entries))
            for rune_entry in rune_entries:
                pyord_rune = rune_from_str(rune_entry["spaced_rune"])
                rune = (
                    dbsession.query(Rune)
                    .filter_by(bridge_id=self.bridge_id, n=pyord_rune.n)
                    .one_or_none()
                )
                if not rune:
                    logger.info("Creating rune %s (%s)", pyord_rune, rune_entry)
                    rune = Rune(
                        bridge_id=self.bridge_id,
                        n=pyord_rune.n,
                        name=pyord_rune.name,
                        symbol=rune_entry["symbol"],
                        spaced_name=rune_entry["spaced_rune"],
                        divisibility=rune_entry["divisibility"],
                        turbo=rune_entry["turbo"],
                    )
                    dbsession.add(rune)
                    dbsession.flush()

            logger.info("Indexing %s transactions", len(transactions))
            for tx in transactions:
                tx_confirmations = tx["confirmations"]
                txid = tx["txid"]
                vout = tx["vout"]
                btc_address = tx["address"]
                ord_output = tx["ord_output"]
                if ord_output:
                    assert ord_output["indexed"]

                btc_tx = (
                    dbsession.query(IncomingBtcTx)
                    .filter_by(
                        bridge_id=self.bridge_id,
                        tx_id=txid,
                        vout=vout,
                    )
                    .one_or_none()
                )
                if btc_tx:
                    logger.info("Updating IncomingBtcTx %s:%s: %s", txid, vout, btc_tx)
                else:
                    logger.info("Creating new IncomingBtcTx %s:%s", txid, vout)
                    btc_tx = IncomingBtcTx(
                        bridge_id=self.bridge_id,
                        tx_id=txid,
                        vout=vout,
                        status=IncomingBtcTxStatus.DETECTED,
                    )
                    dbsession.add(btc_tx)

                if (
                    tx_confirmations >= required_confirmations
                    and btc_tx.status == IncomingBtcTxStatus.DETECTED
                ):
                    btc_tx.status = IncomingBtcTxStatus.ACCEPTED
                btc_tx.block_number = tx.get("blockheight")
                btc_tx.time = tx["time"]
                btc_tx.amount_sat = int(tx["amount"] * 100_000_000)
                btc_tx.address = btc_address
                dbsession.flush()

                deposit_address = (
                    dbsession.query(DepositAddress).filter_by(btc_address=btc_address).one_or_none()
                )
                if not deposit_address:
                    logger.warning("No deposit address found for %s", tx)
                    continue

                btc_tx.user_id = deposit_address.user_id
                dbsession.flush()

                evm_address = deposit_address.user.evm_address

                logger.info(
                    "found transfer: %s:%s, user %s with %s confirmations",
                    txid,
                    vout,
                    evm_address,
                    tx_confirmations,
                )

                if not ord_output:
                    logger.info("Ord output not yet indexed, will be scanned later")
                    continue

                logger.info(
                    "Received %s runes in outpoint %s:%s (user %s)",
                    len(ord_output["runes"]),
                    txid,
                    vout,
                    evm_address,
                )

                if not ord_output["runes"]:
                    logger.warning(
                        "Transfer without runes: %s:%s. ord output: %s",
                        txid,
                        vout,
                        ord_output,
                    )
                    continue

                for spaced_rune_name, balance_entry in ord_output["runes"]:
                    pyord_rune = rune_from_str(spaced_rune_name)
                    rune = (
                        dbsession.query(Rune)
                        .filter_by(bridge_id=self.bridge_id, n=pyord_rune.n)
                        .one()
                    )
                    amounts = self._calculate_rune_to_evm_transfer_amounts(
                        amount_raw=balance_entry["amount"],
                        divisibility=balance_entry["divisibility"],
                    )
                    logger.info(
                        "Received %s %s for %s at %s:%s",
                        amounts.amount_decimal,
                        spaced_rune_name,
                        evm_address,
                        txid,
                        vout,
                    )

                    deposit = (
                        dbsession.query(RuneDeposit)
                        .filter_by(
                            bridge_id=self.bridge_id,
                            tx_id=txid,
                            vout=vout,
                            rune_number=rune.n,
                        )
                        .one_or_none()
                    )
                    if deposit:
                        logger.info("Updating deposit %s", deposit.id)
                    else:
                        logger.info("Creating new deposit")
                        deposit = RuneDeposit(
                            bridge_id=self.bridge_id,
                            tx_id=txid,
                            vout=vout,
                            rune_number=rune.n,
                            status=RuneDepositStatus.DETECTED,
                        )
                        dbsession.add(deposit)

                    deposit.incoming_btc_tx_id = btc_tx.id
                    deposit.block_number = tx["blockheight"]
                    deposit.user_id = deposit_address.user_id
                    deposit.postage = ord_output["value"]
                    deposit.transfer_amount_raw = balance_entry["amount"]
                    deposit.net_amount_raw = amounts.net_amount_raw
                    deposit.rune_id = rune.id
                    if (
                        tx_confirmations >= required_confirmations
                        and deposit.status == RuneDepositStatus.DETECTED
                    ):
                        deposit.status = RuneDepositStatus.ACCEPTED
                    dbsession.flush()

                    logger.info("Deposit: %s", deposit)
                    num_transfers += 1

            check = key_value_store.get_value(last_block_key, default_value=None)
            if check != last_bitcoin_block:
                raise RuntimeError(
                    f"Last block changed from {last_bitcoin_block} to {check} while processing deposits!"
                )
            key_value_store.set_value(last_block_key, new_last_block)
        return num_transfers

    def _sync_ord_with_bitcoind(self, timeout=60):
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
            self._sleep()
        else:
            raise TimeoutError("ORD did not sync in time")

    def get_last_scanned_bitcoin_block(self, dbsession: Session) -> str | None:
        # TODO: temporary code, remove
        last_block_key = f"{self.bridge_name}:btc:deposits:last_scanned_block"
        val = dbsession.query(KeyValuePair).filter_by(key=last_block_key).one_or_none()
        return val.value if val else None

    def get_pending_deposits_for_evm_address(
        self,
        evm_address: str,
        last_block: str,
        dbsession: Session,
    ) -> list[dict]:
        evm_address = eth_utils.to_checksum_address(evm_address)
        logger.info("Getting transactions for %s since %s", evm_address, last_block)
        user = (
            dbsession.query(User)
            .filter_by(
                evm_address=evm_address,
                bridge_id=self.bridge_id,
            )
            .one_or_none()
        )
        if not user:
            logger.info("No user found for %s", evm_address)
            return []

        if len(last_block) != 64:
            logger.info("Invalid block hash length %s", last_block)
            return []

        block_time = self._get_block_time_by_hash(last_block)
        if not block_time:
            logger.info("Invalid block hash %s", last_block)
            return []

        deposit_address = user.deposit_address
        if not deposit_address:
            logger.info("No deposit address found for %s", evm_address)
            return []

        logger.info("User %s has deposit address %s", evm_address, deposit_address.btc_address)
        btc_transactions = (
            dbsession.query(IncomingBtcTx)
            .filter_by(
                bridge_id=self.bridge_id,
                user_id=user.id,
            )
            .filter(
                IncomingBtcTx.time >= block_time,
            )
            .order_by(
                IncomingBtcTx.time,
            )
            .all()
        )

        deposits = []
        for tx in btc_transactions:
            if tx.status == IncomingBtcTxStatus.DETECTED and not tx.rune_deposits:
                logger.info("Found detected tx %s", tx.id)
                deposits.append(
                    {
                        "btc_deposit_txid": tx.tx_id,
                        "btc_deposit_vout": tx.vout,
                        "rune_name": "",
                        "rune_symbol": "",
                        "amount_decimal": "0",
                        "fee_amount_decimal": "0",
                        "receive_amount_decimal": "0",
                        "status": "detected",
                        "evm_transfer_tx_hash": None,
                    }
                )
            else:
                for rune_deposit in tx.rune_deposits:
                    rune = rune_deposit.rune

                    # TODO: use token symbol? but for now we just hardcode POWA
                    if rune.spaced_name == "POWA•RANGERS•GO":
                        symbol = "POWA"
                    else:
                        symbol = rune.symbol

                    deposits.append(
                        {
                            "btc_deposit_txid": rune_deposit.tx_id,
                            "btc_deposit_vout": rune_deposit.vout,
                            "rune_name": rune.spaced_name,
                            "rune_symbol": symbol,
                            "amount_decimal": str(
                                rune.decimal_amount(rune_deposit.transfer_amount_raw)
                            ),
                            "fee_decimal": str(rune.decimal_amount(rune_deposit.fee_raw)),
                            "receive_amount_decimal": str(
                                rune.decimal_amount(rune_deposit.net_amount_raw)
                            ),
                            "status": rune_deposit.get_status_for_ui(),
                            "evm_transfer_tx_hash": rune_deposit.evm_tx_hash,
                        }
                    )

        return deposits

    def _get_block_time_by_hash(self, block_hash) -> int | None:
        try:
            block = self.bitcoin_rpc.call("getblock", block_hash)
            return block["time"]
        except Exception as e:
            logger.info("Invalid block hash %s (%s)", block_hash, e)
            return None

    def get_accepted_rune_deposit_ids(self):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposits = (
                dbsession.query(RuneDeposit)
                .filter_by(
                    bridge_id=self.bridge_id,
                    status=RuneDepositStatus.ACCEPTED,
                )
                .order_by(
                    RuneDeposit.id,
                )
            )
            return [deposit.id for deposit in deposits]

    def get_sign_rune_to_evm_transfer_question(
        self, deposit_id: int
    ) -> messages.SignRuneToEvmTransferQuestion:
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = (
                dbsession.query(RuneDeposit)
                .filter_by(
                    bridge_id=self.bridge_id,
                    id=deposit_id,
                )
                .one()
            )
            if deposit.status != RuneDepositStatus.ACCEPTED:
                raise ValidationError(f"Deposit {deposit} not accepted (got {deposit.status})")
            return messages.SignRuneToEvmTransferQuestion(
                transfer=messages.RuneToEvmTransfer(
                    evm_address=deposit.user.evm_address,
                    amount_raw=deposit.transfer_amount_raw,
                    amount_decimal=deposit.rune.decimal_amount(deposit.transfer_amount_raw),
                    net_amount_raw=deposit.net_amount_raw,
                    txid=deposit.tx_id,
                    vout=deposit.vout,
                    rune_name=deposit.rune.name,
                    rune_number=deposit.rune.n,
                )
            )

    def validate_rune_deposit_for_sending(self, deposit_id: int) -> bool:
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = (
                dbsession.query(RuneDeposit)
                .filter_by(
                    bridge_id=self.bridge_id,
                    id=deposit_id,
                )
                .one()
            )
            deposit_repr = repr(deposit)
            if deposit.status != RuneDepositStatus.ACCEPTED:
                logger.info("Deposit %s has invalid status", deposit_repr)
                return False
            rune_number = deposit.rune.n
            rune_name = deposit.rune.name
            postage = deposit.postage
        if not self.rune_bridge_contract.functions.isRuneRegistered(rune_number).call():
            logger.info("Rune %s for deposit %s is not registered", rune_name, deposit_repr)
            return False
        if postage < self.config.btc_min_postage_sat:
            logger.info("Deposit %s has insufficient postage %s", deposit_repr, postage)
            return False
        return True

    def update_rune_deposit_signatures(
        self,
        deposit_id: int,
        message_hash: str,
        answers: list[messages.SignRuneToEvmTransferAnswer],
    ) -> bool:
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = (
                dbsession.query(RuneDeposit)
                .filter_by(
                    bridge_id=self.bridge_id,
                    id=deposit_id,
                )
                .one()
            )
            logger.info("Updating signatures for deposit %s", deposit)
            if deposit.status != RuneDepositStatus.ACCEPTED:
                raise ValidationError(f"Deposit {deposit} not accepted (got {deposit.status})")

            deposit.accept_transfer_message_hash = message_hash
            signatures = deposit.accept_transfer_signatures
            signers = deposit.accept_transfer_signers
            answers = self._prune_invalid_sign_rune_to_evm_transfer_answers(
                message_hash=message_hash,
                answers=answers,
            )
            for answer in answers:
                if answer.signer not in signers:
                    signers.append(answer.signer)
                    signatures.append(answer.signature)
            dbsession.flush()
            return len(signatures) >= self.get_runes_to_evm_num_required_signers()

    def send_rune_deposit_to_evm(self, deposit_id: int):
        if self.is_bridge_frozen():
            logger.info("Bridge is frozen, cannot send deposits to EVM")
            return

        num_required_signers = self.get_runes_to_evm_num_required_signers()
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = (
                dbsession.query(RuneDeposit)
                .filter_by(
                    bridge_id=self.bridge_id,
                    id=deposit_id,
                )
                .one()
            )
            logger.info("Executing Rune-to-EVM transfer %s", deposit)
            if deposit.status != RuneDepositStatus.ACCEPTED:
                raise ValidationError(f"Deposit {deposit} not accepted (got {deposit.status})")

            signatures = deposit.accept_transfer_signatures
            if len(signatures) < num_required_signers:
                logger.info("Don't have enough signatures for transfer %s", deposit)
                return
            signatures = signatures[:num_required_signers]
            deposit.status = RuneDepositStatus.SENDING_TO_EVM
            evm_address = deposit.user.evm_address
            rune_number = deposit.rune_number
            net_rune_amount = deposit.net_amount_raw
            btc_txid = deposit.tx_id
            btc_vout = deposit.vout

        try:
            tx_hash = self.rune_bridge_contract.functions.acceptTransferFromBtc(
                evm_address,
                rune_number,
                net_rune_amount,
                eth_utils.add_0x_prefix(btc_txid),
                btc_vout,
                signatures,
            ).transact(
                {
                    "gas": 500_000,
                }
            )
            logger.info("Sent Rune-to-EVM transfer %s, waiting...", tx_hash.hex())
        except Exception as e:
            logger.exception("Error sending Rune-to-EVM transfer")
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                deposit = dbsession.get(RuneDeposit, deposit_id)
                deposit.status = RuneDepositStatus.SENDING_TO_EVM_FAILED
            raise e
        else:
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                deposit = dbsession.get(RuneDeposit, deposit_id)
                deposit.status = RuneDepositStatus.SENT_TO_EVM
                deposit.evm_tx_hash = tx_hash.hex()

        self._confirm_sent_rune_deposit(deposit_id)

    def confirm_sent_rune_deposits(self):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposits = dbsession.query(RuneDeposit).filter_by(
                bridge_id=self.bridge_id,
                status=RuneDepositStatus.SENT_TO_EVM,
            )
            ids = [deposit.id for deposit in deposits]
        for id in ids:
            self._confirm_sent_rune_deposit(id)

    def _confirm_sent_rune_deposit(self, deposit_id: int):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = dbsession.get(RuneDeposit, deposit_id)
            if deposit.status == RuneDepositStatus.SENT_TO_EVM:
                try:
                    receipt = self.web3.eth.get_transaction_receipt(deposit.evm_tx_hash)
                except (TransactionNotFound, TransactionIndexingInProgress):
                    receipt = None

                if receipt:
                    if receipt["status"]:
                        deposit.status = RuneDepositStatus.CONFIRMED_IN_EVM
                        logger.info("Rune-to-EVM transfer %s confirmed", deposit)
                    else:
                        deposit.status = RuneDepositStatus.EVM_TRANSACTION_FAILED
                        logger.warning("Rune-to-EVM transfer %s failed", deposit)
                else:
                    logger.info("Rune-to-EVM transfer %s not yet confirmed", deposit)
            else:
                logger.warning("Deposit %s not in SENT_TO_EVM state", deposit)

    def answer_sign_rune_to_evm_transfer_question(
        self,
        message: messages.SignRuneToEvmTransferQuestion,
    ) -> messages.SignRuneToEvmTransferAnswer:
        transfer = message.transfer
        rune_response = self.ord_client.get_rune(transfer.rune_name)
        if not rune_response:
            raise ValidationError(f"Rune {transfer.rune_name} not found (transfer {transfer})")

        rune = rune_from_str(transfer.rune_name)
        if not rune.n == transfer.rune_number:
            raise ValidationError(f"Rune number mismatch: {rune}.n != {transfer.rune_number}")

        if not self.rune_bridge_contract.functions.isRuneRegistered(rune.n).call():
            raise ValidationError(f"Rune {rune} not registered")

        divisibility = rune_response["entry"]["divisibility"]
        calculated_amounts = self._calculate_rune_to_evm_transfer_amounts(
            amount_raw=transfer.amount_raw,
            divisibility=divisibility,
        )
        if transfer.amount_raw != calculated_amounts.amount_raw:
            raise ValidationError(
                f"Amount mismatch: {transfer.amount_decimal!r} != {calculated_amounts.amount_raw}"
            )

        if transfer.net_amount_raw != calculated_amounts.net_amount_raw:
            raise ValidationError(
                f"Net amount mismatch: {transfer.net_amount_raw} != {calculated_amounts.net_amount_raw}"
            )
        if transfer.net_amount_raw == 0:
            raise ValidationError("Net amount is zero")

        balance_at_output = self.ord_multisig.get_rune_balance_at_output(
            txid=transfer.txid,
            vout=transfer.vout,
            rune_name=transfer.rune_name,
        )
        if balance_at_output != transfer.amount_raw:
            raise ValidationError(
                f"Balance at output {transfer.txid}:{transfer.vout} is {balance_at_output}, "
                f"expected {transfer.amount_raw}"
            )

        # TODO: validate that the deposit address belongs to our wallet
        # TODO: validate the deposit address belongs to the user
        # user = self.get_user_by_deposit_address(deposit_address=transfer.evm_address)
        # if not user:
        #     raise ValidationError(f"User not found for deposit address {transfer.evm_address}")
        # if not user.evm_address == transfer.evm_address:
        #     raise ValidationError(f"User EVM address mismatch: {user.evm_address} != {transfer.evm_address}")

        message_hash = self.rune_bridge_contract.functions.getAcceptTransferFromBtcMessageHash(
            transfer.evm_address,
            rune.n,
            transfer.net_amount_raw,
            eth_utils.add_0x_prefix(transfer.txid),
            transfer.vout,
        ).call()
        signable_message = encode_defunct(primitive=message_hash)
        signed_message = self.evm_account.sign_message(signable_message)
        return messages.SignRuneToEvmTransferAnswer(
            signature=signed_message.signature.hex(),
            signer=self.evm_account.address,
            message_hash=eth_utils.to_hex(message_hash),
        )

    def _prune_invalid_sign_rune_to_evm_transfer_answers(
        self, *, message_hash: bytes | str, answers: list[messages.SignRuneToEvmTransferAnswer]
    ) -> list[messages.SignRuneToEvmTransferAnswer]:
        signers = set()
        ret = []
        for answer in answers:
            if answer.signer in signers:
                logger.warning("already signed by %s", answer.signer)
                continue
            try:
                self.validate_sign_rune_to_evm_transfer_answer(
                    message_hash=message_hash,
                    answer=answer,
                )
            except ValidationError:
                logger.exception("Validation error")
                logger.info("Encountered validation error, pruning")
            else:
                ret.append(answer)
                signers.add(answer.signer)
        return ret

    def validate_sign_rune_to_evm_transfer_answer(
        self, *, message_hash: bytes | str, answer: messages.SignRuneToEvmTransferAnswer
    ):
        is_federator = self.rune_bridge_contract.functions.isFederator(answer.signer).call()
        if not is_federator:
            raise ValidationError(f"Signer {answer.signer} is not a federator")

        message_hash = HexBytes(message_hash)
        signable_message = encode_defunct(primitive=message_hash)
        recovered = recover_message(
            signable_message,
            HexBytes(answer.signature),
        )
        if recovered != answer.signer:
            raise ValidationError(
                f"Recovered signer {recovered} does not match expected {answer.signer}"
            )

    def answer_sign_rune_token_to_btc_transfer_question(
        self,
        message: messages.SignRuneTokenToBtcTransferQuestion,
    ) -> messages.SignRuneTokenToBtcTransferAnswer:
        unsigned_psbt = self.ord_multisig.deserialize_psbt(message.unsigned_psbt_serialized)
        # TODO: recreate the psbt here

        hex_tx = unsigned_psbt.unsigned_tx.serialize().hex()
        runestone = pyord.Runestone.decipher_hex(hex_tx)
        if not runestone:
            raise ValidationError("Could not decipher runestone from hex tx")
        if runestone.is_cenotaph:
            raise ValidationError(f"Runestone is a cenotaph: {runestone}")
        if len(runestone.edicts) != 1:
            raise ValidationError(f"Expected 1 edict, got {len(runestone.edicts)}")
        # edict = runestone.edicts[0]
        # psbt_output = unsigned_psbt.outputs[edict.output]
        # TODO: actually validate it

        # TODO: validate the transfer happened on the smart contract side
        signed_psbt = self.ord_multisig.sign_psbt(unsigned_psbt)
        return messages.SignRuneTokenToBtcTransferAnswer(
            signed_psbt_serialized=self.ord_multisig.serialize_psbt(signed_psbt),
            signer_xpub=self.ord_multisig.signer_xpub,
        )

    def _get_rune_to_evm_transfer_key_value_store_key(
        self, transfer: messages.RuneToEvmTransfer
    ) -> str:
        return f"{self.bridge_name}:rune-to-evm-transfer:{transfer.txid}:{transfer.vout}:{transfer.rune_name}"

    def scan_rune_token_deposits(self) -> int:
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            key_value_store = tx.find_service(KeyValueStore)

            num_transfers = 0

            def callback(batch: list[EventData]):
                nonlocal num_transfers
                for event in batch:
                    print(event)
                    if event["event"] == "RuneTransferToBtc":
                        rune = (
                            dbsession.query(Rune)
                            .filter_by(
                                bridge_id=self.bridge_id,
                                n=event["args"]["rune"],
                            )
                            .one_or_none()
                        )
                        if not rune:
                            pyord_rune = pyord.Rune(n=event["args"]["rune"])
                            rune_response = self.ord_client.get_rune(pyord_rune.name)
                            if not rune_response:
                                raise RuntimeError(f"Rune {pyord_rune.name} not found in ord")
                            rune_entry = rune_response["entry"]
                            rune = Rune(
                                bridge_id=self.bridge_id,
                                n=pyord_rune.n,
                                name=pyord_rune.name,
                                symbol=rune_entry["symbol"],
                                spaced_name=rune_entry["spaced_rune"],
                                divisibility=rune_entry["divisibility"],
                                turbo=rune_entry["turbo"],
                            )
                            logger.info("Created new rune: %s", rune)
                            dbsession.add(rune)
                            dbsession.flush()
                        deposit = RuneTokenDeposit(
                            bridge_id=self.bridge_id,
                            evm_block_number=event["blockNumber"],
                            evm_tx_hash=event["transactionHash"].hex(),
                            evm_log_index=event["logIndex"],
                            rune_id=rune.id,
                            receiver_btc_address=event["args"]["receiverBtcAddress"],
                            token_address=event["args"]["token"],
                            net_rune_amount_raw=event["args"]["netRuneAmount"],
                            transferred_token_amount=event["args"]["transferredTokenAmount"],
                            status=RuneTokenDepositStatus.ACCEPTED,
                        )
                        dbsession.add(deposit)
                        dbsession.flush()
                        num_transfers += 1
                    else:
                        logger.warning("Unknown event: %s", event)

            scanner = EvmEventScanner(
                web3=self.web3,
                events=[
                    self.rune_bridge_contract.events.RuneTransferToBtc,
                ],
                callback=callback,
                dbsession=dbsession,
                block_safety_margin=self.config.evm_block_safety_margin,
                key_value_store=key_value_store,
                key_value_store_namespace=self.bridge_name,
                default_start_block=self.config.evm_default_start_block,
            )
            scanner.scan_new_events()

        return num_transfers

    def get_accepted_rune_token_deposit_ids(self):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposits = (
                dbsession.query(RuneTokenDeposit)
                .filter_by(
                    bridge_id=self.bridge_id,
                    status=RuneTokenDepositStatus.ACCEPTED,
                )
                .order_by(
                    RuneTokenDeposit.id,
                )
            )
            return [deposit.id for deposit in deposits]

    def handle_accepted_rune_token_deposit(
        self,
        deposit_id: int,
        ask_signatures: Callable[
            [messages.SignRuneTokenToBtcTransferQuestion],
            list[messages.SignRuneTokenToBtcTransferAnswer],
        ],
    ):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = (
                dbsession.query(RuneTokenDeposit)
                .filter_by(
                    bridge_id=self.bridge_id,
                    id=deposit_id,
                )
                .one()
            )
            logger.info("Processing RuneToken->BTC deposit %s", deposit)
            if deposit.status != RuneTokenDepositStatus.ACCEPTED:
                raise ValidationError(f"Deposit {deposit} not accepted (got {deposit.status})")
            if deposit.net_rune_amount_raw == 0:
                raise ValidationError("Net amount is zero")
            transfer = messages.RuneTokenToBtcTransfer(
                receiver_address=deposit.receiver_btc_address,
                rune_name=deposit.rune.n,
                token_address=deposit.token_address,
                net_rune_amount=deposit.net_rune_amount_raw,
            )

        fee_rate_sats_per_vb = self._btc_fee_estimator.get_fee_sats_per_vb()
        logger.info("Fee rate: %s sats/vb", fee_rate_sats_per_vb)
        num_required_signatures = self.get_rune_tokens_to_btc_num_required_signers()
        unsigned_psbt = self.ord_multisig.create_rune_psbt(
            fee_rate_sat_per_vbyte=fee_rate_sats_per_vb,
            transfers=[
                RuneTransfer(
                    rune=transfer.rune_name,
                    receiver=transfer.receiver_address,
                    amount=transfer.net_rune_amount,
                )
            ],
        )
        message = messages.SignRuneTokenToBtcTransferQuestion(
            transfer=transfer,
            unsigned_psbt_serialized=self.ord_multisig.serialize_psbt(unsigned_psbt),
            fee_rate_sats_per_vb=fee_rate_sats_per_vb,
        )
        self_response = self.answer_sign_rune_token_to_btc_transfer_question(message=message)
        self_signed_psbt = self.ord_multisig.deserialize_psbt(self_response.signed_psbt_serialized)
        logger.info("Asking for signatures for RuneToken->BTC transfer %s", transfer)
        responses = ask_signatures(message)
        signed_psbts = [self_signed_psbt]
        signed_psbts.extend(
            self.ord_multisig.deserialize_psbt(response.signed_psbt_serialized)
            for response in responses
        )
        signed_psbts = signed_psbts[:num_required_signatures]

        # TODO: validate responses

        if len(signed_psbts) < num_required_signatures:
            logger.info(
                "Not enough signatures for transfer: %s (got %s, expected %s)",
                transfer,
                len(signed_psbts),
                num_required_signatures,
            )
            return

        finalized_psbt = self.ord_multisig.combine_and_finalize_psbt(
            initial_psbt=unsigned_psbt,
            signed_psbts=signed_psbts,
        )

        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = dbsession.get(RuneTokenDeposit, deposit_id)
            assert deposit.status == RuneTokenDepositStatus.ACCEPTED
            deposit.status = RuneTokenDepositStatus.SENDING_TO_BTC
            deposit.finalized_psbt = self.ord_multisig.serialize_psbt(finalized_psbt)
            dbsession.flush()

        txid = self.ord_multisig.broadcast_psbt(finalized_psbt)

        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = dbsession.get(RuneTokenDeposit, deposit_id)
            assert deposit.status == RuneTokenDepositStatus.SENDING_TO_BTC
            deposit.status = RuneTokenDepositStatus.SENT_TO_BTC
            deposit.btc_tx_id = txid
            dbsession.flush()

    def get_user_by_deposit_address(self, deposit_address: str) -> User | None:
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            obj = dbsession.scalars(
                sa.select(DepositAddress)
                .join(User)
                .filter(
                    User.bridge_id == self.bridge_id,
                    DepositAddress.btc_address == deposit_address,
                )
            ).one_or_none()
            if not obj:
                return None
            return obj.user

    def get_runes_to_evm_num_required_signers(self) -> int:
        return self.rune_bridge_contract.functions.numRequiredFederators().call()

    def get_rune_tokens_to_btc_num_required_signers(self) -> int:
        return self.ord_multisig.num_required_signers

    def get_evm_to_runes_num_required_signers(self) -> int:
        return self.ord_multisig.num_required_signers

    def is_bridge_frozen(self) -> bool:
        return self.rune_bridge_contract.functions.frozen().call()

    def _sleep(self, multiplier: float = 1.0):
        time.sleep(1.0 * multiplier)

    def _calculate_rune_to_evm_transfer_amounts(
        self, amount_raw: int, divisibility: int
    ) -> TransferAmounts:
        if not isinstance(amount_raw, int):
            raise ValueError(f"Amount must be int, got {amount_raw!r}")
        if not isinstance(divisibility, int):
            raise ValueError(f"Divisibility must be int, got {divisibility!r}")

        divisor = 10**divisibility
        amount_decimal = Decimal(amount_raw) / divisor
        fee_decimal = amount_decimal * self.config.runes_to_evm_fee_percentage_decimal / 100
        net_amount_decimal = amount_decimal - fee_decimal
        net_amount_raw = int(net_amount_decimal * divisor)
        fee_raw = amount_raw - net_amount_raw

        return TransferAmounts(
            amount_decimal=amount_decimal,
            amount_raw=amount_raw,
            fee_decimal=fee_decimal,
            fee_raw=fee_raw,
            net_amount_decimal=net_amount_decimal,
            net_amount_raw=net_amount_raw,
        )

    def _get_rune_token(self, rune_number: int) -> Contract:
        address = self.rune_bridge_contract.functions.getTokenByRune(rune_number).call()
        return self.web3.eth.contract(
            address=address,
            abi=load_rune_bridge_abi("RuneToken"),
        )
