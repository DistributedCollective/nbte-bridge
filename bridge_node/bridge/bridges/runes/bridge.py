import logging
import time

from bridge.common.interfaces.bridge import Bridge
from bridge.common.p2p.network import Network
from .service import RuneBridgeService
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

        # TODO: make it more robust:
        # - store these first in the DB
        # - then retrieve from DB

        rune_deposits = self.service.scan_rune_deposits()
        # self-sign is implicit
        num_required_signatures = self.service.get_runes_to_evm_num_required_signers()
        logger.info("Found %s Rune->EVM deposits", len(rune_deposits))
        for deposit in rune_deposits:
            logger.info("Processing Rune->EVM deposit %s", deposit)
            tries_left = self.max_retries + 1
            message = messages.SignRuneToEvmTransferQuestion(
                transfer=deposit,
            )
            self_response = self.service.answer_sign_rune_to_evm_transfer_question(message=message)
            self_signature = self_response.signature
            while tries_left > 0:
                tries_left -= 1
                logger.info("Asking for signatures for deposit %s", deposit)
                responses = self.network.ask(
                    question=self.sign_rune_to_evm_transfer_question,
                    message=message,
                )
                signatures = [self_signature]
                signatures.extend(response.signature for response in responses)
                signatures = signatures[:num_required_signatures]
                # TODO: validate received signatures
                # - test sender is federator
                # - test recovered matches sender
                if len(signatures) >= num_required_signatures:
                    break
                logger.warning(
                    "Not enough signatures for transfer: %s, trying again soon",
                    deposit,
                )
                time.sleep(self.max_retries - tries_left + 1)
            else:
                logger.error("Failed to get enough signatures for transfer: %s", deposit)
                continue

            self.service.send_rune_to_evm(deposit, signatures=signatures)

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
                        # TODO: handle divisibility
                        amount=deposit.net_rune_amount,
                    )
                ]
            )
            message = messages.SignRuneTokenToBtcTransferQuestion(
                transfer=deposit,
                unsigned_psbt_serialized=self.service.ord_multisig.serialize_psbt(unsigned_psbt),
            )
            tries_left = self.max_retries + 1
            while tries_left > 0:
                tries_left -= 1
                logger.info("Asking for signatures for RuneToken->BTC deposit %s")
                responses = self.network.ask(
                    question=self.sign_rune_token_to_btc_transfer_question,
                    message=message,
                )
                signed_psbts = [
                    self.service.ord_multisig.deserialize_psbt(response.signed_psbt_serialized)
                    for response in responses[:num_required_signatures]
                ]
                # TODO: validate responses
                if len(signed_psbts) >= num_required_signatures:
                    break
                logger.warning(
                    "Not enough signatures for transfer: %s",
                    deposit,
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
