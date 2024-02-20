import logging

from typing import TypedDict
from anemic.ioc import Container, auto, autowired, service
from sqlalchemy.orm.session import Session
from hexbytes import HexBytes
from eth_utils import add_0x_prefix
from eth_account.messages import encode_defunct

from .models import (
    SerializedTapToRskTransferBatch,
    TapToRskTransfer,
    TapToRskTransferBatch,
    TapToRskTransferBatchStatus,
)
from .rsk import BridgeContract
from .config import Config
from bridge.common.evm.account import Account
from bridge.common.p2p.network import Network
from bridge.common.services.transactions import TransactionManager
from bridge.common.tap.client import TapRestClient
from bridge.common.evm.utils import recover_message
from bridge.common.evm.provider import Web3


logger = logging.getLogger(__name__)


SIGN_TRANSFER_BATCH_QUESTION = "taprsk-sign-tap-to-rsk"


class SignTransferBatchAnswer(TypedDict):
    signatures: list[str]
    signer: str


@service(scope="global")
class TapToRskService:
    transaction_manager: TransactionManager = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    tap_client: TapRestClient = autowired(auto)
    batch_limit: int = 10
    network: Network = autowired(auto)
    config: Config = autowired(auto)
    rsk_account: Account = autowired(auto)
    web3: Web3 = autowired(auto)

    def __init__(self, container: Container):
        self.container = container

    def init(self):
        self.network.answer_with(SIGN_TRANSFER_BATCH_QUESTION, self._answer_sign_transfer_batch)

    def process_current_transfer_batch(self):
        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            current_batch = self._get_or_create_current_batch(dbsession)
            if not current_batch:
                logger.info("No current TAP to RSK batch")
                return
            logger.info("Current TAP to RSK batch: %s", current_batch)
            batch_id, status = current_batch.id, current_batch.status
            num_transfers = len(current_batch.transfers)
            signatures_by_signer = current_batch.signatures.copy()
            serialized_batch = current_batch.serialize()

        if status == TapToRskTransferBatchStatus.CREATED:
            # TODO: hack since we don't support more than one batch per transfer yet
            federators = self.bridge_contract.functions.getFederators().call()
            num_required_signers = self.bridge_contract.functions.numRequiredSigners().call()
            num_required_signers -= 1  # self-sign is implicit
            signature_responses = self.network.ask(
                question=SIGN_TRANSFER_BATCH_QUESTION,
                serialized_batch=serialized_batch,
            )
            for response in signature_responses:
                if response["signer"] not in federators:
                    logger.warning("Signer %s not in federators", response["signer"])
                    continue
                if len(response["signatures"]) != num_transfers:
                    logger.warning(
                        "Invalid number of signatures from %s: %s",
                        response["signer"],
                        response["signatures"],
                    )
                    continue

                ok = True
                for transfer, signature in zip(
                    serialized_batch["transfers"], response["signatures"]
                ):
                    message_hash = self.bridge_contract.functions.getTransferFromTapMessageHash(
                        transfer["deposit_address"]["rsk_address"],
                        transfer["deposit_address"]["tap_address"],
                        add_0x_prefix(transfer["deposit_btc_tx_id"]),
                        transfer["deposit_btc_tx_vout"],
                    ).call()
                    signable_message = encode_defunct(primitive=message_hash)
                    recovered = recover_message(
                        signable_message,
                        signature,
                    )
                    if recovered != response["signer"]:
                        logger.warning(
                            "Invalid signature from %s: %s", response["signer"], signature
                        )
                        ok = False
                        break

                if not ok:
                    continue

                signatures_by_signer[response["signer"]] = response["signatures"]

            # self-sign is ok
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                current_batch = dbsession.query(TapToRskTransferBatch).get(batch_id)
                current_batch.signatures = signatures_by_signer
                if len(current_batch.signatures.keys()) >= num_required_signers:
                    status = current_batch.status = TapToRskTransferBatchStatus.SIGNATURES_COLLECTED
                    logger.info("Batch %s signed", batch_id)
                dbsession.flush()

        if status == TapToRskTransferBatchStatus.SIGNATURES_COLLECTED:
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                current_batch = dbsession.query(TapToRskTransferBatch).get(batch_id)

                accept_transfer_calls = [
                    [
                        transfer.deposit_address.rsk_address,
                        transfer.deposit_address.tap_address,
                        add_0x_prefix(transfer.deposit_btc_tx_id),
                        transfer.deposit_btc_tx_vout,
                        signatures,
                    ]
                    for transfer, signatures in zip(
                        current_batch.transfers, zip(*signatures_by_signer.values())
                    )
                ]

                status = current_batch.status = TapToRskTransferBatchStatus.SENDING_TO_RSK
                dbsession.flush()

            logger.info("Handling %s transfers from Tap to EVM", len(accept_transfer_calls))
            tx_hashes = []
            for call_args in accept_transfer_calls:
                tx_hash = self.bridge_contract.functions.acceptTransferFromTap(*call_args).transact(
                    {
                        "gas": 20_000_000,
                    }
                )
                logger.info("Tx hash %s", tx_hash.hex())
                tx_hashes.append(tx_hash)

            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                current_batch = dbsession.query(TapToRskTransferBatch).get(batch_id)
                status = current_batch.status = TapToRskTransferBatchStatus.SENT_TO_RSK
                current_batch.executed_tx_hash = tx_hashes[-1].hex()  # TODO: send all in one tx
                dbsession.flush()

        if status == TapToRskTransferBatchStatus.SENDING_TO_RSK:
            raise ValueError(
                "TransferBatch got left in SENDING_TO_RSK state, which cannot be resolved automatically"
            )

        if status == TapToRskTransferBatchStatus.SENT_TO_RSK:
            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                current_batch = dbsession.query(TapToRskTransferBatch).get(batch_id)
                tx_hash = current_batch.executed_tx_hash

            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, poll_latency=2)
            if not receipt.status:
                raise ValueError(f"Tx {tx_hash} failed")

            with self.transaction_manager.transaction() as tx:
                dbsession = tx.find_service(Session)
                current_batch = dbsession.query(TapToRskTransferBatch).get(batch_id)
                status = current_batch.status = TapToRskTransferBatchStatus.FINALIZED
                dbsession.flush()

    def _get_or_create_current_batch(self, dbsession: Session) -> TapToRskTransferBatch | None:
        current_batch = (
            dbsession.query(
                TapToRskTransferBatch,
            )
            .filter(
                TapToRskTransferBatch.status != TapToRskTransferBatchStatus.FINALIZED,
            )
            .order_by(
                TapToRskTransferBatch.id.asc(),
            )
            .first()
        )
        if current_batch:
            return current_batch

        # Create a new batch
        transfers = (
            dbsession.query(TapToRskTransfer)
            .filter(
                TapToRskTransfer.transfer_batch_id.is_(None),
            )
            .order_by(TapToRskTransfer.counter)
            .limit(
                self.batch_limit,
            )
            .all()
        )
        if not transfers:
            return None
        current_batch = TapToRskTransferBatch(
            transfers=transfers,
            status=TapToRskTransferBatchStatus.CREATED,
        )
        current_batch.hash = current_batch.compute_hash()
        dbsession.add(current_batch)
        dbsession.flush()
        return current_batch

    def _answer_sign_transfer_batch(
        self,
        *,
        serialized_batch: SerializedTapToRskTransferBatch,
    ) -> SignTransferBatchAnswer:
        if self.network.is_leader():
            raise ValueError("Leader doesn't answer to anyone")

        # TODO: revamp batch signing logic
        # TODO: validate that the message is from the leader
        if serialized_batch["status"] != TapToRskTransferBatchStatus.CREATED:
            raise ValueError("Only created batches can be signed")

        my_address: str = self.rsk_account.address
        if my_address in serialized_batch["signatures"]:
            return SignTransferBatchAnswer(
                signatures=serialized_batch["signatures"][my_address],
                signer=self.rsk_account.address,
            )

        with self.transaction_manager.transaction() as tx:
            dbsession = tx.find_service(Session)
            existing_batch = (
                dbsession.query(TapToRskTransferBatch)
                .filter_by(
                    hash=HexBytes(serialized_batch["hash"]),
                )
                .first()
            )
            if existing_batch:
                # Don't sign again if we have an existing batch
                return SignTransferBatchAnswer(
                    signatures=existing_batch.signatures[my_address],
                    signer=self.rsk_account.address,
                )

            transfer_batch = TapToRskTransferBatch(
                hash=HexBytes(serialized_batch["hash"]),
                status=TapToRskTransferBatchStatus.CREATED,
                signatures=serialized_batch["signatures"],  # just accept signatures as-is for now
            )
            my_signatures = transfer_batch.signatures[my_address] = []

            for transfer in serialized_batch["transfers"]:
                btc_tx_id = transfer["deposit_btc_tx_id"]
                btc_tx_vout = transfer["deposit_btc_tx_vout"]
                if self.bridge_contract.functions.isProcessed(
                    add_0x_prefix(btc_tx_id),
                    btc_tx_vout,
                ).call():
                    raise ValueError(f"Transfer {transfer} already processed")

                # TODO: check that the transfer is in database instead of blindly accepting it!
                # existing_transfer = dbsession.query(TapToRskTransfer).filter_by(
                #     deposit_btc_tx_id=btc_tx_id,
                #     deposit_btc_tx_vout=btc_tx_vout,
                # ).first()
                # if not existing_transfer:
                #     raise ValueError(f"Transfer {transfer} not found in the database")
                # if existing_transfer.transfer_batch_id:
                #     raise ValueError(f"Transfer {transfer} already in a batch {existing_transfer.transfer_batch}")
                # transfer_batch.transfers.append(existing_transfer)

                # TODO: validate proofs!

                message_hash = self.bridge_contract.functions.getTransferFromTapMessageHash(
                    transfer["deposit_address"]["rsk_address"],
                    transfer["deposit_address"]["tap_address"],
                    add_0x_prefix(btc_tx_id),
                    btc_tx_vout,
                ).call()
                signable_message = encode_defunct(primitive=message_hash)
                signed_message = self.rsk_account.sign_message(signable_message)
                signature = signed_message.signature.hex()
                my_signatures.append(signature)

            # TODO: re-enable this too
            # computed_hash = transfer_batch.compute_hash()
            # if computed_hash != transfer_batch.hash:
            #     raise ValueError(f"Computed hash {computed_hash} does not match given hash for batch {transfer_batch}")
            dbsession.add(transfer_batch)
            dbsession.flush()

            return SignTransferBatchAnswer(
                signatures=my_signatures,
                signer=self.rsk_account.address,
            )
