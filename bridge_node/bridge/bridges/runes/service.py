import dataclasses
import functools
import itertools
import logging
import time
from collections.abc import Callable
from decimal import Decimal
from typing import (
    Protocol,
)

import eth_utils
import pyord
import sqlalchemy as sa
from bitcointx.core.script import CScript
from bitcointx.wallet import CCoinAddress
from eth_account.account import LocalAccount
from eth_account.messages import encode_defunct
from hexbytes import HexBytes
from sqlalchemy.orm import (
    Session,
)
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import (
    TransactionIndexingInProgress,
    TransactionNotFound,
)
from web3.types import EventData

from bridge.common.btc.fees import BitcoinFeeEstimator
from bridge.common.btc.rpc import BitcoinRPC

from ...common.btc.types import BitcoinNetwork
from ...common.evm.scanner import EvmEventScanner
from ...common.evm.utils import (
    from_wei,
    recover_message,
)
from ...common.messengers import Messenger, NullMessenger
from ...common.models.key_value_store import KeyValuePair
from ...common.ord.client import OrdApiClient
from ...common.ord.multisig import (
    OrdMultisig,
    RuneTransfer,
)
from ...common.ord.transfers import TARGET_POSTAGE_SAT
from ...common.ord.types import (
    rune_from_str,
)
from ...common.services.key_value_store import KeyValueStore
from ...common.services.transactions import TransactionManager
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
    btc_max_fee_rate_sats_per_vbyte: int


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
        messenger: Messenger | None = None,
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
        self._get_block_number_by_hash = functools.lru_cache(256)(self._get_block_number_by_hash)
        self.logger = logging.getLogger(f"{__name__}:{self.bridge_name}")
        if messenger is None:
            self._messenger = NullMessenger()
        else:
            self._messenger = messenger

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

    def check(self) -> None:
        self.ord_multisig.check()

    def generate_deposit_address(self, *, evm_address: str, dbsession: Session) -> str:
        # TODO: dbsession now passed as parameter, seems ugly?
        try:
            evm_address = eth_utils.to_checksum_address(evm_address)
        except Exception as e:
            raise ValueError(f"Invalid EVM address: {evm_address}") from e

        user = dbsession.query(User).filter_by(bridge_id=self.bridge_id, evm_address=evm_address).first()
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
                f"listsinceblock_buffer ({listsinceblock_buffer}) must be "
                f">= required_confirmations ({required_confirmations})"
            )

        if not last_bitcoin_block:
            self.logger.info("Scanning Rune deposits from the beginning")
            resp = self.bitcoin_rpc.call("listsinceblock", "", listsinceblock_buffer)
        else:
            self.logger.info("Scanning Rune deposits from block %s", last_bitcoin_block)
            resp = self.bitcoin_rpc.call(
                "listsinceblock",
                last_bitcoin_block,
                listsinceblock_buffer,
            )

        # Sync with Bitcoind to avoid missing rune outputs
        self._sync_ord_with_bitcoind()

        # New last block will be stored in the DB
        new_last_block = resp["lastblock"]
        self.logger.debug("New last block: %s", new_last_block)

        # Filter invalid transactions and map ord_output outside of db transaction
        # Also keep track of newly seen runes
        rune_names = set()
        transactions = []
        for tx in resp["transactions"]:
            if tx["category"] != "receive":
                continue

            btc_address = tx.get("address")
            if not btc_address:
                self.logger.warning("No BTC address in transaction %s", tx)
                continue

            if btc_address == self.ord_multisig.change_address:
                self.logger.debug("Ignoring tx to change address %s", btc_address)
                continue

            txid = tx["txid"]
            vout = tx["vout"]
            tx_confirmations = tx["confirmations"]
            ord_output = tx["ord_output"] = None
            if tx_confirmations > 0:
                self.logger.debug("tx: %s", tx)
                # TXs without confirmations are not indexed by ord
                retries = 10
                for i in range(retries):
                    ord_output = self.ord_client.get_output(txid, vout)
                    if ord_output["indexed"]:
                        tx["ord_output"] = ord_output
                        break
                    if ord_output["spent"]:
                        # ORD drops spent outputs from the index and no longer shows the rune balances for them
                        # this is a problem, because
                        # 1) we have the listsinceblock buffer
                        # 2) a node that's down a while might not get to index an output
                        # From my understanding, it's hard to do this properly right now.
                        # See https://github.com/ordinals/ord/issues/3723
                        self.logger.warning("Unindexed spent output %s:%s (%s), ignoring", txid, vout, ord_output)
                        break
                    self.logger.info("Output %s:%s (%s) not indexed in ord yet, waiting", txid, vout, ord_output)
                    self._sleep(i)
                else:
                    raise RuntimeError(f"Output not indexed in ord after {retries} tries")

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

            self.logger.debug("Indexing %s runes", len(rune_entries))
            for rune_entry in rune_entries:
                pyord_rune = rune_from_str(rune_entry["spaced_rune"])
                rune = dbsession.query(Rune).filter_by(bridge_id=self.bridge_id, n=pyord_rune.n).one_or_none()
                if not rune:
                    self.logger.info("Indexing rune %s (%s)", pyord_rune, rune_entry)
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

            self.logger.debug("Indexing %s transactions", len(transactions))
            for tx in transactions:
                tx_confirmations = tx["confirmations"]
                txid = tx["txid"]
                vout = tx["vout"]
                btc_address = tx["address"]
                ord_output = tx["ord_output"]
                if ord_output:
                    if not ord_output["indexed"]:
                        raise AssertionError(f"Output {txid}:{vout} not indexed in ord")

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
                    self.logger.debug("Updating IncomingBtcTx %s:%s: %s", txid, vout, btc_tx)
                else:
                    self.logger.info("New IncomingBtcTx detected: %s:%s", txid, vout)
                    btc_tx = IncomingBtcTx(
                        bridge_id=self.bridge_id,
                        tx_id=txid,
                        vout=vout,
                        status=IncomingBtcTxStatus.DETECTED,
                    )
                    dbsession.add(btc_tx)
                    self._messenger.send_message(
                        title=f"[{self.bridge_name}] New incoming BTC transaction",
                        message=f"BTC tx: `{txid}:{vout}`\nUser address: `{btc_address}`",
                    )

                if tx_confirmations >= required_confirmations and btc_tx.status == IncomingBtcTxStatus.DETECTED:
                    btc_tx.status = IncomingBtcTxStatus.ACCEPTED
                btc_tx.block_number = tx.get("blockheight")
                btc_tx.time = tx["time"]
                btc_tx.amount_sat = int(tx["amount"] * 100_000_000)
                btc_tx.address = btc_address
                dbsession.flush()

                deposit_address = dbsession.query(DepositAddress).filter_by(btc_address=btc_address).one_or_none()
                if not deposit_address:
                    self.logger.warning("No deposit address found for %s", tx)
                    continue

                btc_tx.user_id = deposit_address.user_id
                dbsession.flush()

                evm_address = deposit_address.user.evm_address

                self.logger.info(
                    "found transfer: %s:%s, user %s with %s confirmations",
                    txid,
                    vout,
                    evm_address,
                    tx_confirmations,
                )

                if not ord_output:
                    self.logger.info("Ord output not yet indexed, will be scanned later")
                    continue

                self.logger.debug(
                    "Transaction contains %s runes in outpoint %s:%s (user %s)",
                    len(ord_output["runes"]),
                    txid,
                    vout,
                    evm_address,
                )

                if not ord_output["runes"]:
                    self.logger.warning(
                        "Transfer without runes: %s:%s. ord output: %s",
                        txid,
                        vout,
                        ord_output,
                    )
                    continue

                for spaced_rune_name, balance_entry in ord_output["runes"]:
                    pyord_rune = rune_from_str(spaced_rune_name)
                    rune = dbsession.query(Rune).filter_by(bridge_id=self.bridge_id, n=pyord_rune.n).one()
                    amounts = self._calculate_rune_to_evm_transfer_amounts(
                        amount_raw=balance_entry["amount"],
                        divisibility=balance_entry["divisibility"],
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
                        self.logger.debug(
                            "Updating deposit %s (%s %s for %s at %s:%s)",
                            deposit.id,
                            amounts.amount_decimal,
                            spaced_rune_name,
                            evm_address,
                            txid,
                            vout,
                        )
                    else:
                        self.logger.info(
                            "Received new Rune deposit: %s %s for %s at %s:%s",
                            amounts.amount_decimal,
                            spaced_rune_name,
                            evm_address,
                            txid,
                            vout,
                        )
                        deposit = RuneDeposit(
                            bridge_id=self.bridge_id,
                            tx_id=txid,
                            vout=vout,
                            rune_number=rune.n,
                            status=RuneDepositStatus.DETECTED,
                        )
                        dbsession.add(deposit)
                        self._messenger.send_message(
                            title=f"[{self.bridge_name}] New Rune deposit",
                            message=(
                                f"Deposit: `{amounts.amount_decimal} {spaced_rune_name}`\n"
                                f"BTC Tx: `{txid}:{vout}`\n"
                                f"User (evm): `{evm_address}`\nUser (btc): `{btc_address}`"
                            ),
                        )

                    deposit.incoming_btc_tx_id = btc_tx.id
                    deposit.block_number = tx["blockheight"]
                    deposit.user_id = deposit_address.user_id
                    deposit.postage = ord_output["value"]
                    deposit.transfer_amount_raw = balance_entry["amount"]
                    deposit.net_amount_raw = amounts.net_amount_raw
                    deposit.rune_id = rune.id
                    if tx_confirmations >= required_confirmations and deposit.status == RuneDepositStatus.DETECTED:
                        assert deposit.status == RuneDepositStatus.DETECTED
                        deposit.status = RuneDepositStatus.ACCEPTED
                    dbsession.flush()

                    self.logger.debug("Deposit: %s", deposit)
                    num_transfers += 1

            check = key_value_store.get_value(last_block_key, default_value=None)
            if check != last_bitcoin_block:
                raise RuntimeError(
                    f"Last block changed from {last_bitcoin_block} to " f"{check} while processing deposits!"
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
            self.logger.info(
                "Waiting for ord to sync to block %d (current: %d)",
                bitcoind_block_count,
                ord_block_count,
            )
            self._sleep()
        else:
            raise TimeoutError("ORD did not sync in time")

    def get_last_scanned_bitcoin_block(self, dbsession: Session) -> str | None:
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
        self.logger.debug("Getting transactions for %s since %s", evm_address, last_block)
        user = (
            dbsession.query(User)
            .filter_by(
                evm_address=evm_address,
                bridge_id=self.bridge_id,
            )
            .one_or_none()
        )
        if not user:
            self.logger.debug("No user found for %s", evm_address)
            return []

        if len(last_block) != 64:
            self.logger.debug("Invalid block hash length %s", last_block)
            return []

        block_time = self._get_block_time_by_hash(last_block)
        if not block_time:
            self.logger.debug("Invalid block hash %s", last_block)
            return []

        block_number = self._get_block_number_by_hash(last_block)
        block_number += self.config.btc_listsinceblock_buffer

        deposit_address = user.deposit_address
        if not deposit_address:
            self.logger.debug("No deposit address found for %s", evm_address)
            return []

        self.logger.debug("User %s has deposit address %s", evm_address, deposit_address.btc_address)
        pending_btc_transactions = (
            dbsession.query(IncomingBtcTx)
            .filter_by(
                bridge_id=self.bridge_id,
                user_id=user.id,
                status=IncomingBtcTxStatus.DETECTED,
            )
            .filter(
                IncomingBtcTx.time >= block_time,
            )
            .order_by(
                IncomingBtcTx.time,
            )
            .all()
        )
        accepted_btc_transactions = (
            dbsession.query(IncomingBtcTx)
            .filter_by(
                bridge_id=self.bridge_id,
                user_id=user.id,
                status=IncomingBtcTxStatus.ACCEPTED,
            )
            .filter(
                IncomingBtcTx.block_number >= block_number,
            )
            .order_by(
                IncomingBtcTx.block_number,
            )
            .all()
        )

        btc_transactions = pending_btc_transactions + accepted_btc_transactions

        deposits = []
        for tx in btc_transactions:
            if tx.status == IncomingBtcTxStatus.DETECTED and not tx.rune_deposits:
                self.logger.debug("Found detected tx %s", tx.id)
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
                            "amount_decimal": str(rune.decimal_amount(rune_deposit.transfer_amount_raw)),
                            "fee_decimal": str(rune.decimal_amount(rune_deposit.fee_raw)),
                            "receive_amount_decimal": str(rune.decimal_amount(rune_deposit.net_amount_raw)),
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
            self.logger.info("Invalid block hash %s (%s)", block_hash, e)
            return None

    def _get_block_number_by_hash(self, block_hash) -> int | None:
        try:
            block = self.bitcoin_rpc.call("getblock", block_hash)
            return block["height"]
        except Exception as e:
            self.logger.info("Invalid block hash %s (%s)", block_hash, e)
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

    def get_sign_rune_to_evm_transfer_question(self, deposit_id: int) -> messages.SignRuneToEvmTransferQuestion:
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
                self.logger.warning("Deposit %s has invalid status", deposit_repr)
                return False
            rune_number = deposit.rune.n
            rune_name = deposit.rune.name
            postage = deposit.postage
        if not self.rune_bridge_contract.functions.isRuneRegistered(rune_number).call():
            self.logger.warning("Rune %s for deposit %s is not registered", rune_name, deposit_repr)
            return False
        if postage < self.config.btc_min_postage_sat:
            self.logger.warning("Deposit %s has insufficient postage %s", deposit_repr, postage)
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
            self.logger.info("Updating signatures for deposit %s", deposit)
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
            num_required = self.get_runes_to_evm_num_required_signers()
            self.logger.debug(
                "Got %s signatures for deposit %s, required: %s",
                len(signatures),
                deposit,
                num_required,
            )
            return len(signatures) >= num_required

    def send_rune_deposit_to_evm(self, deposit_id: int):
        if self.is_bridge_frozen():
            self.logger.info("Bridge is frozen, cannot send deposits to EVM")
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
            self.logger.info("Executing Rune-to-EVM transfer %s", deposit)
            if deposit.status != RuneDepositStatus.ACCEPTED:
                raise ValidationError(f"Deposit {deposit} not accepted (got {deposit.status})")

            signatures = deposit.accept_transfer_signatures
            if len(signatures) < num_required_signers:
                self.logger.info("Don't have enough signatures for transfer %s", deposit)
                return
            signatures = signatures[:num_required_signers]
            deposit.status = RuneDepositStatus.SENDING_TO_EVM
            evm_address = deposit.user.evm_address
            rune_number = deposit.rune_number
            net_rune_amount = deposit.net_amount_raw
            btc_txid = deposit.tx_id
            btc_vout = deposit.vout
            rune_name = deposit.rune.spaced_name
            net_amount_decimal = deposit.rune.decimal_amount(net_rune_amount)

        tx_gas_limit = 250_000  # actual gas usage is somewhere around 95k-115k, but let's be safe
        tx_gas_price = self.web3.eth.gas_price
        balance_wei = self.web3.eth.get_balance(
            self.evm_account.address,
            block_identifier="pending",
        )
        min_balance_wei = int(1.2 * tx_gas_limit * tx_gas_price)
        if balance_wei < min_balance_wei:
            raise RuntimeError(
                f"Insufficient balance in EVM account ({from_wei(balance_wei)} < {from_wei(min_balance_wei)}) -- "
                "cannot execute Runes-to-EVM transfer"
            )

        # set nonce explicitly to avoid overriding our own transactions
        nonce = self.web3.eth.get_transaction_count(
            self.evm_account.address,
            block_identifier="pending",
        )

        num_pending_transactions = nonce - self.web3.eth.get_transaction_count(
            self.evm_account.address,
            block_identifier="latest",
        )

        # RSK has a hard limit of 4 transactions in mempool per address -- just hardcode this for all chains for now
        # Raising an exception here is fine, transactions will just be resumed
        if num_pending_transactions >= 4:
            raise RuntimeError(
                f"We have {num_pending_transactions} pending transactions, which is greater than 4. "
                "Trying again later.",
            )

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
                    "gas": tx_gas_limit,
                    "nonce": nonce,
                }
            )
            self.logger.info("Sent Rune-to-EVM transfer %s, waiting...", tx_hash.hex())
            self._messenger.send_message(
                title=f"[{self.bridge_name}] Rune-to-EVM transfer sent to EVM",
                message=(
                    f"EVM Tx: `{tx_hash.hex()}`\n"
                    f"Deposit: `{btc_txid}:{btc_vout}` (rune `{rune_name}`)\n"
                    f"Transfer: `{net_amount_decimal} {rune_name}`"
                ),
            )
        except Exception as e:
            self.logger.exception("Error sending Rune-to-EVM transfer")
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                deposit = dbsession.get(RuneDeposit, deposit_id)
                assert deposit.bridge_id == self.bridge_id
                deposit.status = RuneDepositStatus.SENDING_TO_EVM_FAILED
            self._messenger.send_message(
                title=f"[{self.bridge_name}] Sending Rune-to-EVM transfer to EVM failed!",
                message=(
                    f"Deposit: `{btc_txid}:{btc_vout}` (rune `{rune_name}`)\n"
                    f"Transfer: `{net_amount_decimal} {rune_name}`"
                ),
                alert=True,
            )
            raise e
        else:
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                deposit = dbsession.get(RuneDeposit, deposit_id)
                assert deposit.bridge_id == self.bridge_id
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
        for deposit_id in ids:
            self._confirm_sent_rune_deposit(deposit_id)

    def _confirm_sent_rune_deposit(self, deposit_id: int):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            deposit = dbsession.get(RuneDeposit, deposit_id)
            assert deposit.bridge_id == self.bridge_id
            existing_status = deposit.status
            evm_tx_hash = deposit.evm_tx_hash
            deposit_repr = repr(deposit)

        updated_status = None
        if existing_status == RuneDepositStatus.SENT_TO_EVM:
            try:
                receipt = self.web3.eth.get_transaction_receipt(evm_tx_hash)
            except (TransactionNotFound, TransactionIndexingInProgress):
                receipt = None

            if receipt:
                if receipt["status"]:
                    updated_status = RuneDepositStatus.CONFIRMED_IN_EVM
                    self.logger.info("Rune-to-EVM transfer %s confirmed", deposit_repr)
                    self._messenger.send_message(
                        title=f"[{self.bridge_name}] Rune-to-EVM transfer confirmed in EVM",
                        message=f"EVM Tx:`{evm_tx_hash}`\nDeposit: `{deposit_repr}`",
                    )
                else:
                    updated_status = RuneDepositStatus.EVM_TRANSACTION_FAILED
                    self.logger.warning("Rune-to-EVM transfer %s failed", deposit_repr)
                    self._messenger.send_message(
                        title=f"[{self.bridge_name}] Rune-to-EVM transfer in EVM failed!",
                        message=f"EVM Tx:`{evm_tx_hash}`\nDeposit: `{deposit_repr}`",
                        alert=True,
                    )
            else:
                self.logger.info("Rune-to-EVM transfer %s not yet confirmed", deposit_repr)
        else:
            self.logger.error("Deposit %s not in SENT_TO_EVM state", deposit_repr)

        if updated_status is not None:
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                deposit = dbsession.get(RuneDeposit, deposit_id)
                assert deposit.status == RuneDepositStatus.SENT_TO_EVM
                deposit.status = updated_status

    def answer_sign_rune_to_evm_transfer_question(
        self,
        message: messages.SignRuneToEvmTransferQuestion,
    ) -> messages.SignRuneToEvmTransferAnswer:
        self.logger.info("Answering request to sign Rune->EVM transfer. Message: %s", message)
        transfer = message.transfer
        # with self.transaction_manager.transaction() as tx:
        #     dbsession = tx.find_service(Session)
        #     deposit = (
        #         dbsession.query(RuneDeposit)
        #         .filter_by(
        #             bridge_id=self.bridge_id,
        #             tx_id=transfer.txid,
        #             vout=transfer.vout,
        #             rune_number=transfer.rune_number,
        #         )
        #         .one_or_none()
        #     )
        #     if not deposit:
        #         raise ValidationError(f"Deposit {transfer.txid}:{transfer.vout}:{transfer.rune_number} not found")
        #     if deposit.status != RuneDepositStatus.ACCEPTED:
        #         raise ValidationError(f"Deposit {deposit} not accepted (got {deposit.status})")
        #     if deposit.user.evm_address != transfer.evm_address:
        #         # TODO: cannot do this yet
        #         raise ValidationError(f"Deposit {deposit} EVM address mismatch")

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
            raise ValidationError(f"Amount mismatch: {transfer.amount_decimal!r} != {calculated_amounts.amount_raw}")

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
        self,
        *,
        message_hash: bytes | str,
        answers: list[messages.SignRuneToEvmTransferAnswer],
    ) -> list[messages.SignRuneToEvmTransferAnswer]:
        signers = set()
        ret = []
        for answer in answers:
            if answer.signer in signers:
                self.logger.warning("already signed by %s", answer.signer)
                continue
            try:
                self.validate_sign_rune_to_evm_transfer_answer(
                    message_hash=message_hash,
                    answer=answer,
                )
            except ValidationError:
                self.logger.exception("Validation error")
                self.logger.info("Encountered validation error, pruning")
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
            raise ValidationError(f"Recovered signer {recovered} does not match expected {answer.signer}")

    def answer_sign_rune_token_to_btc_transfer_question(
        self,
        message: messages.SignRuneTokenToBtcTransferQuestion,
    ) -> messages.SignRuneTokenToBtcTransferAnswer:
        # Prepare for API change -- message will have multiple transfers in the future
        transfers = getattr(message, "transfers", None)
        if transfers is None:
            transfers = [message.transfer]
        num_transfers = len(transfers)
        num_unique_transfers = len(set((transfer.event_tx_hash, transfer.event_log_index) for transfer in transfers))
        if num_unique_transfers != num_transfers:
            raise ValidationError(f"Duplicate transfers: {transfers}")

        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            for transfer in transfers:
                deposit = (
                    dbsession.query(RuneTokenDeposit)
                    .filter_by(
                        bridge_id=self.bridge_id,
                        evm_tx_hash=transfer.event_tx_hash,
                        evm_log_index=transfer.event_log_index,
                    )
                    .one()
                )
                # This validates that the transfer happened on the smart contract side and is seen by us
                if deposit.status != RuneTokenDepositStatus.ACCEPTED:
                    raise ValidationError(
                        f"Deposit {deposit} not accepted (got {deposit.status} (transfer: {transfer}))"
                    )

                receiver_btc_address = deposit.receiver_btc_address
                if receiver_btc_address != transfer.receiver_address:
                    raise ValidationError(
                        f"Receiver BTC address mismatch: {receiver_btc_address} != {transfer.receiver_address} "
                        f"(transfer: {transfer}))"
                    )
                if deposit.net_rune_amount_raw != transfer.net_rune_amount:
                    raise ValidationError(
                        f"Net rune amount mismatch: {deposit.net_rune_amount_raw} != {transfer.net_rune_amount} "
                        f"(transfer: {transfer}))"
                    )

                rune = rune_from_str(transfer.rune_name)
                if deposit.rune.n != rune.n:
                    raise ValidationError(f"Rune number mismatch: {deposit.rune.n} != {rune.n} (transfer: {transfer}))")
                if rune.n != transfer.rune_number:
                    raise ValidationError(
                        f"Rune number/name mismatch: {rune.n} != {transfer.rune_number}  (transfer: {transfer}))"
                    )

                if deposit.net_rune_amount_raw != transfer.net_rune_amount:
                    raise ValidationError(
                        f"Net rune amount mismatch: {deposit.net_rune_amount_raw} != {transfer.net_rune_amount} "
                        f"(transfer: {transfer}))"
                    )

        unsigned_psbt = self.ord_multisig.deserialize_psbt(message.unsigned_psbt_serialized)

        unsigned_tx = unsigned_psbt.unsigned_tx
        hex_tx = unsigned_tx.serialize().hex()
        runestone = pyord.Runestone.decipher_hex(hex_tx)
        if not runestone:
            raise ValidationError("Could not decipher runestone from hex tx")
        if runestone.is_cenotaph:
            raise ValidationError(f"Runestone is a cenotaph: {runestone}")

        # NOTE: for now, we expect:
        # output 0: Runestone with an edict for each transfer
        # output 1: amount = postage (10k sat), to = change_address
        # outputs 2...N-2: amount = postage (10k sat), to = user address
        # output N-1: bitcoin change to our address

        if len(unsigned_tx.vout) not in (num_transfers + 2, num_transfers + 3):
            # output for each transfer, op return, rune change output, and possibly btc change output
            raise ValidationError(
                f"Expected {num_transfers + 2}-{num_transfers + 3} outputs, got {len(unsigned_tx.vout)}"
            )

        expected_postage = TARGET_POSTAGE_SAT
        if unsigned_tx.vout[0].nValue != 0:
            raise ValidationError(f"Expected value 0 OP_RETURN at output 0, {unsigned_tx.vout[0].nValue}")
        if unsigned_tx.vout[0].scriptPubKey != CScript(runestone.encipher()):
            raise ValidationError("Expected runestone at output 0")
        if unsigned_tx.vout[1].nValue != expected_postage:
            raise ValidationError(f"Expected postage {expected_postage} at output 2, got {unsigned_tx.vout[1].nValue}")
        if unsigned_tx.vout[1].scriptPubKey != self.ord_multisig.change_script_pubkey:
            raise ValidationError(
                f"Expected script pubkey {self.ord_multisig.change_script_pubkey!r} of the change address "
                f"{self.ord_multisig.change_address!r} at output 1, got {unsigned_tx.vout[1].scriptPubKey!r}"
            )

        if len(unsigned_tx.vout) == num_transfers + 3:
            # Validate the change output only if we have it
            if unsigned_tx.vout[-1].scriptPubKey != self.ord_multisig.change_script_pubkey:
                raise ValidationError(
                    f"Expected change address {self.ord_multisig.change_script_pubkey} at last output"
                )

        if len(runestone.edicts) != num_transfers:
            raise ValidationError(f"Expected {num_transfers} edicts, got {len(runestone.edicts)}")

        for transfer_vout, (edict, transfer) in enumerate(
            itertools.zip_longest(runestone.edicts, transfers),
            start=2,
        ):
            rune_response = self.ord_client.get_rune(transfer.rune_name)
            if not rune_response:
                raise ValidationError(f"Rune {rune.name} not found in ord")

            rune_id = pyord.RuneId.from_str(rune_response["id"])

            edict = runestone.edicts[0]
            if edict.amount != transfer.net_rune_amount:
                raise ValidationError(
                    f"Amount mismatch: {edict.amount} != {transfer.net_rune_amount} "
                    f"(transfer: {transfer} @ {transfer_vout})"
                )
            if edict.id != rune_id:
                raise ValidationError(
                    f"Rune ID mismatch: {edict.id} != {rune_id} (transfer: {transfer} @ {transfer_vout})"
                )
            if edict.output != transfer_vout:
                raise ValidationError(f"Expected output {transfer_vout}, got {edict.output} (transfer: {transfer})")

            if unsigned_tx.vout[transfer_vout].nValue != expected_postage:
                raise ValidationError(
                    f"Expected postage {expected_postage} at output {transfer_vout}, "
                    f"got {unsigned_tx.vout[transfer_vout].nValue} (transfer: {transfer})"
                )

            expected_parsed_address = CCoinAddress(transfer.receiver_address)
            script_pubkey = unsigned_tx.vout[transfer_vout].scriptPubKey
            if script_pubkey != expected_parsed_address.to_scriptPubKey():
                raise ValidationError(
                    f"Expected script pubkey {expected_parsed_address.to_scriptPubKey()} "
                    "(address {expected_parsed_address}) at output {transfer_vout}, "
                    f"got {script_pubkey} (transfer: {transfer})"
                )

        expected_fee_rate_sat_per_vb = self._btc_fee_estimator.get_fee_sats_per_vb()
        fee_rate_margin = 3
        min_fee_rate = self._get_min_fee_rate_sat_per_vbyte()
        fee_rate_min = max(expected_fee_rate_sat_per_vb // fee_rate_margin, min_fee_rate)
        fee_rate_max = max(expected_fee_rate_sat_per_vb, min_fee_rate) * fee_rate_margin
        if fee_rate_min > message.fee_rate_sats_per_vb or fee_rate_max < message.fee_rate_sats_per_vb:
            raise ValidationError(
                f"Fee rate {message.fee_rate_sats_per_vb} not within range [{fee_rate_min}, {fee_rate_max}]"
            )

        psbt_size = self.ord_multisig.estimate_psbt_size_vb(unsigned_psbt)
        calculated_fee = psbt_size * message.fee_rate_sats_per_vb
        actual_fee = unsigned_psbt.get_fee()
        fee_margin = 1.1
        if actual_fee >= calculated_fee * fee_margin:
            raise ValidationError(f"Fee {actual_fee} too high, expected max {calculated_fee * fee_margin}")
        if actual_fee < calculated_fee / fee_margin:
            raise ValidationError(f"Fee {actual_fee} too low, expected min {calculated_fee / fee_margin}")

        signed_psbt = self.ord_multisig.sign_psbt(unsigned_psbt)
        return messages.SignRuneTokenToBtcTransferAnswer(
            signed_psbt_serialized=self.ord_multisig.serialize_psbt(signed_psbt),
            signer_xpub=self.ord_multisig.signer_xpub,
        )

    def scan_rune_token_deposits(self) -> int:
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            key_value_store = tx.find_service(KeyValueStore)

            num_transfers = 0

            def callback(batch: list[EventData]):
                nonlocal num_transfers
                for event in batch:
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
                            self.logger.info("Created new rune: %s", rune)
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
                        # TODO: add decimal amount to message
                        self._messenger.send_message(
                            title=f"[{self.bridge_name}] New Rune Token deposit",
                            message=(
                                f"Deposit: `{deposit.transferred_token_amount}` wei of `{rune.spaced_name}`\n"
                                f"Receiver: `{deposit.receiver_btc_address}`\n"
                                f"EVM tx: `{deposit.evm_tx_hash}`\n"
                                f"EVM log index: `{deposit.evm_log_index}`\n"
                            ),
                        )
                    else:
                        self.logger.warning("Unknown event: %s", event)

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
            self.logger.info("Processing RuneToken->BTC deposit %s", deposit)
            if deposit.status != RuneTokenDepositStatus.ACCEPTED:
                raise ValidationError(f"Deposit {deposit} not accepted (got {deposit.status})")
            if deposit.net_rune_amount_raw == 0:
                raise ValidationError("Net amount is zero")
            transfer = messages.RuneTokenToBtcTransfer(
                receiver_address=deposit.receiver_btc_address,
                rune_number=deposit.rune.n,
                rune_name=deposit.rune.name,
                token_address=deposit.token_address,
                net_rune_amount=deposit.net_rune_amount_raw,
                event_tx_hash=deposit.evm_tx_hash,
                event_log_index=deposit.evm_log_index,
            )

        fee_rate_sats_per_vb = self._btc_fee_estimator.get_fee_sats_per_vb()
        self.logger.info("Fee rate: %s sats/vb", fee_rate_sats_per_vb)
        if fee_rate_sats_per_vb > self.config.btc_max_fee_rate_sats_per_vbyte:
            raise RuntimeError(
                f"Fee rate is humongous ({fee_rate_sats_per_vb} > {self.config.btc_max_fee_rate_sats_per_vbyte}), "
                f"refusing to proceed with transfer",
            )

        margin = 1.1  # TODO: hardcoded margin
        fee_rate_sats_per_vb = int(margin * fee_rate_sats_per_vb)
        min_fee_rate = self._get_min_fee_rate_sat_per_vbyte()
        fee_rate_sats_per_vb = max(fee_rate_sats_per_vb, min_fee_rate)
        self.logger.info("Adjusted fee rate: %s sats/vb", fee_rate_sats_per_vb)

        num_required_signatures = self.get_rune_tokens_to_btc_num_required_signers()
        unsigned_psbt = self.ord_multisig.create_rune_psbt(
            fee_rate_sat_per_vbyte=fee_rate_sats_per_vb,
            transfers=[
                RuneTransfer(
                    rune=transfer.rune_number,
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
        self.logger.info("Asking for signatures for RuneToken->BTC transfer %s", transfer)
        responses = ask_signatures(message)
        signed_psbts = [self_signed_psbt]
        signed_psbts.extend(
            self.ord_multisig.deserialize_psbt(response.signed_psbt_serialized) for response in responses
        )
        signed_psbts = signed_psbts[:num_required_signatures]

        # TODO: validate responses

        if len(signed_psbts) < num_required_signatures:
            self.logger.warning(
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

        try:
            txid = self.ord_multisig.broadcast_psbt(finalized_psbt)
        except Exception as e:
            self.logger.exception("Error broadcasting RuneToken->BTC transfer")
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                deposit = dbsession.get(RuneTokenDeposit, deposit_id)
                deposit.status = RuneTokenDepositStatus.SENDING_TO_BTC_FAILED
                self._messenger.send_message(
                    title=f"[{self.bridge_name}] Broadcasting Rune PSBT to Bitcoin failed!",
                    message=f"Deposit: `{deposit}`\nTransfer: `{transfer}",
                    alert=True,
                )
            raise e

        self._messenger.send_message(
            title=f"[{self.bridge_name}] Rune PSBT broadcast to Bitcoin",
            message=f"BTC Tx: `{txid}`\nTransfer: `{transfer}`\n",
        )

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

    def _calculate_rune_to_evm_transfer_amounts(self, amount_raw: int, divisibility: int) -> TransferAmounts:
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

    def get_rune_token(self, rune_number: int) -> Contract:
        address = self.rune_bridge_contract.functions.getTokenByRune(rune_number).call()
        return self.web3.eth.contract(
            address=address,
            abi=load_rune_bridge_abi("RuneToken"),
        )

    def _get_min_fee_rate_sat_per_vbyte(self) -> int:
        # Try to avoid the situation where a tx gets stuck forever, even if we technically can CPFP
        if self.config.btc_network == "mainnet":
            return 15
        return 1
