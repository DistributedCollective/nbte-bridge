import logging
import time

from bridge.common.interfaces.bridge import Bridge
from bridge.common.p2p.network import Network
from .service import (
    RuneBridgeService,
)
from . import messages
from ...common.ord.transfers import RuneTransfer

logger = logging.getLogger(__name__)


class RuneBridge(Bridge):
    def __init__(
        self,
        *,
        bridge_id: str,
        network: Network,
        service: RuneBridgeService,
    ):
        self.bridge_id = bridge_id
        self.name = bridge_id  # Bridge protocol
        self.network = network
        self.service = service

        self.sign_rune_to_evm_transfer_question = f"{bridge_id}:sign-rune-to-evm-transfer"
        self.sign_rune_token_to_btc_transfer_question = (
            f"{bridge_id}:sign-rune-token-to-btc-transfer"
        )
        self.max_retries = 10

    def init(self) -> None:
        self.service.init()
        if not self.network.is_leader():
            self.network.answer_with(
                self.sign_rune_to_evm_transfer_question,
                self._sign_rune_to_evm_transfer_answer,
            )
            self.network.answer_with(
                self.sign_rune_token_to_btc_transfer_question,
                self._sign_rune_token_to_btc_transfer_answer,
            )

    def run_iteration(self) -> None:
        if not self.network.is_leader():
            # TODO: right now, only the leader will run these
            logger.info("Not leader, not doing anything")
            return

        num_deposits = self.service.scan_rune_deposits()
        logger.info("Found %s Rune->EVM deposits", num_deposits)

        self.service.confirm_sent_rune_deposits()

        self._handle_rune_transfers_to_evm()

        self._handle_rune_token_transfers_to_btc()

    def _handle_rune_transfers_to_evm(self):
        if self.service.is_bridge_frozen():
            logger.info("Bridge is frozen, cannot handle deposits to EVM")
            return

        for deposit_id in self.service.get_accepted_rune_deposit_ids():
            try:
                logger.info("Processing Rune->EVM deposit %s", deposit_id)
                if not self.service.validate_rune_deposit_for_sending(deposit_id):
                    continue
                message = self.service.get_sign_rune_to_evm_transfer_question(deposit_id)
                self_response = self.service.answer_sign_rune_to_evm_transfer_question(
                    message=message
                )
                message_hash = self_response.message_hash
                logger.info("Asking for signatures for deposit %s", message)
                responses = self.network.ask(
                    question=self.sign_rune_to_evm_transfer_question,
                    message=message,
                )
                ready_to_send = self.service.update_rune_deposit_signatures(
                    deposit_id, message_hash=message_hash, answers=[self_response] + responses
                )
                if ready_to_send:
                    self.service.send_rune_deposit_to_evm(deposit_id)
                else:
                    logger.info("Not enough signatures for deposit %s", deposit_id)
            except Exception as e:
                logger.exception("Failed to process deposit %s: %s", deposit_id, e)

    def _handle_rune_token_transfers_to_btc(self):
        num_required_signatures = self.service.get_rune_tokens_to_btc_num_required_signers()

        token_deposits = self.service.scan_rune_token_deposits()
        logger.info("Found %s RuneToken->BTC deposits", len(token_deposits))
        for deposit in token_deposits:
            logger.info("Processing RuneToken->BTC deposit %s", deposit)
            # TODO: abstract these behind the service better
            unsigned_psbt = self.service.ord_multisig.create_rune_psbt(
                transfers=[
                    RuneTransfer(
                        rune=deposit.rune_name,
                        receiver=deposit.receiver_address,
                        amount=deposit.net_rune_amount,
                    )
                ]
            )
            message = messages.SignRuneTokenToBtcTransferQuestion(
                transfer=deposit,
                unsigned_psbt_serialized=self.service.ord_multisig.serialize_psbt(unsigned_psbt),
            )
            self_response = self.service.answer_sign_rune_token_to_btc_transfer_question(
                message=message
            )
            self_signed_psbt = self.service.ord_multisig.deserialize_psbt(
                self_response.signed_psbt_serialized
            )
            tries_left = self.max_retries + 1
            while tries_left > 0:
                tries_left -= 1
                logger.info("Asking for signatures for RuneToken->BTC deposit %s", deposit)
                responses = self.network.ask(
                    question=self.sign_rune_token_to_btc_transfer_question,
                    message=message,
                )
                signed_psbts = [self_signed_psbt]
                signed_psbts.extend(
                    self.service.ord_multisig.deserialize_psbt(response.signed_psbt_serialized)
                    for response in responses
                )
                signed_psbts = signed_psbts[:num_required_signatures]
                # TODO: validate responses
                if len(signed_psbts) >= num_required_signatures:
                    break
                logger.warning(
                    "Not enough signatures for transfer: %s (got %s, expected %s)",
                    deposit,
                    len(signed_psbts),
                    num_required_signatures,
                )
                time.sleep(self.max_retries - tries_left + 1)
            else:
                logger.error("Failed to get enough signatures for transfer: %s", deposit)
                continue

            signed_psbts.append(self.service.ord_multisig.sign_psbt(unsigned_psbt))
            finalized_psbt = self.service.ord_multisig.combine_and_finalize_psbt(
                initial_psbt=unsigned_psbt,
                signed_psbts=signed_psbts,
            )
            self.service.ord_multisig.broadcast_psbt(finalized_psbt)

    def _sign_rune_to_evm_transfer_answer(self, message):
        # TODO: This is wrapped to make it easier to patch...
        return self.service.answer_sign_rune_to_evm_transfer_question(message=message)

    def _sign_rune_token_to_btc_transfer_answer(self, message):
        # TODO: This is wrapped to make it easier to patch...
        return self.service.answer_sign_rune_token_to_btc_transfer_question(message=message)
