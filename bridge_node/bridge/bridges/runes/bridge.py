import logging

from bridge.common.interfaces.bridge import Bridge
from bridge.common.p2p.network import Network
from .service import (
    RuneBridgeService,
)

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
        num_rune_deposits = self.service.scan_rune_deposits()
        logger.info("Found %s Rune->EVM transfers", num_rune_deposits)
        num_rune_token_deposits = self.service.scan_rune_token_deposits()
        logger.info("Found %s Rune Token->BTC transfers", num_rune_token_deposits)

        self.service.confirm_sent_rune_deposits()

        if not self.network.is_leader():
            return

        if self.service.is_bridge_frozen():
            logger.info("Bridge is frozen, not handling deposits")
            return

        self._handle_rune_transfers_to_evm()
        self._handle_rune_token_transfers_to_btc()

    # TODO: the _handle* methods are written differently and it's ugly

    def _handle_rune_transfers_to_evm(self):
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
                logger.exception("Failed to process Rune->EVM transfer %s: %s", deposit_id, e)

    def _handle_rune_token_transfers_to_btc(self):
        def ask_signatures(message):
            return self.network.ask(
                question=self.sign_rune_token_to_btc_transfer_question,
                message=message,
            )

        for deposit_id in self.service.get_accepted_rune_token_deposit_ids():
            try:
                self.service.handle_accepted_rune_token_deposit(
                    deposit_id,
                    ask_signatures=ask_signatures,
                )
            except Exception as e:
                logger.exception("Failed to process Rune Token -> BTC transfer %s: %s", deposit_id, e)

    def _sign_rune_to_evm_transfer_answer(self, message):
        # TODO: This is wrapped to make it easier to patch...
        return self.service.answer_sign_rune_to_evm_transfer_question(message=message)

    def _sign_rune_token_to_btc_transfer_answer(self, message):
        # TODO: This is wrapped to make it easier to patch...
        return self.service.answer_sign_rune_token_to_btc_transfer_question(message=message)
