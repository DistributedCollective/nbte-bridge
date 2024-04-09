import logging


from bridge.common.interfaces.bridge import Bridge
from bridge.common.p2p.network import Network
from .service import RuneBridgeService
from . import messages


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

    def init(self) -> None:
        if not self.network.is_leader():
            self.network.answer_with(
                self.sign_rune_to_evm_transfer_question,
                self._sign_rune_to_evm_transfer_answer,
            )

    def run_iteration(self) -> None:
        if not self.network.is_leader():
            # TODO: right now, only alice will run these
            return

        # TODO: make it more robust:
        # - store these first in the DB
        # - then retrieve from DB

        rune_deposits = self.service.scan_rune_deposits()
        # self-sign is implicit
        num_required_signatures = self.service.get_runes_to_evm_num_required_signers() - 1
        for deposit in rune_deposits:
            responses = self.network.ask(
                question=self.sign_rune_to_evm_transfer_question,
                message=messages.SignRuneToEvmTransferQuestion(
                    transfer=deposit,
                ),
            )
            # TODO: validate received signatures
            # - test sender is federator
            # - test recovered matches sender
            if len(responses) < num_required_signatures:
                logger.warning(
                    "Not enough signatures for transfer: %s",
                    deposit,
                )
                continue
            signatures = [response.signature for response in responses[:num_required_signatures]]
            self.service.send_rune_to_evm(deposit, signatures=signatures)

        token_deposits = self.service.scan_token_deposits()
        for deposit in token_deposits:
            self.service.send_token_to_btc(deposit)

    def _sign_rune_to_evm_transfer_answer(self, message):
        # TODO: This is wrapped to make it easier to patch...
        return self.service.answer_sign_rune_to_evm_transfer_question(message=message)
