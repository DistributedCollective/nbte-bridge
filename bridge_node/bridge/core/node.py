import logging
import time

from anemic.ioc import autowired, auto, service, Container

from ..btc.types import PSBT
from ..p2p.network import Network
from ..p2p.messaging import MessageEnvelope

from ..evm.scanner import BridgeEventScanner, TransferToBTC
from ..btc.rpc import BitcoinRPC
from ..btc.utils import to_satoshi
from ..btc.multisig import Transfer, BitcoinMultisig
from ..evm.utils import from_wei

logger = logging.getLogger(__name__)


@service(scope="global")
class BridgeNode:
    network: Network = autowired(auto)
    evm_scanner: BridgeEventScanner = autowired(auto)
    bitcoin_rpc: BitcoinRPC = autowired(auto)
    bitcoin_multisig: BitcoinMultisig = autowired(auto)

    def __init__(self, container: Container):
        self.container = container
        self.network.add_listener(self.on_message)
        self.network.answer_with("sign-psbt", self._answer_sign_psbt)

    def on_message(self, envelope: MessageEnvelope):
        logger.debug("Received message %r from node %s", envelope.message, envelope.sender)

        if envelope.message == "Ping":
            self.network.send(envelope.sender, "Pong")

    def ping(self):
        self.network.broadcast("Ping")

    def enter_main_loop(self):
        while True:
            try:
                self._run_iteration()
            except KeyboardInterrupt:
                break
            except Exception:
                logger.exception("Error in main loop")
            time.sleep(10)

    def _run_iteration(self):
        logger.debug("Running main loop iteration from node: %s", self.network.node_id)
        if self.network.is_leader():
            self.ping()
        # TODO: first store to database, then handle the transfers in database (not directly from blockchain)
        events = self.evm_scanner.scan_events()
        transfers_to_btc: list[TransferToBTC] = []
        for event in events:
            match event:
                case TransferToBTC():
                    transfers_to_btc.append(event)
                case _:
                    logger.info("Found unknown event: %s", event)

        if not self.network.is_leader():
            logger.info("Not leader, not doing anything")
            return

        if transfers_to_btc:
            # TODO: should limit max amount of transfers per psbt
            self._handle_transfers_to_btc(transfers_to_btc)

    def _handle_transfers_to_btc(self, transfers: list[TransferToBTC]):
        logger.info("Handling %s transfers to BTC", len(transfers))
        for i, transfer in enumerate(transfers):
            logger.info(
                "#%d: %s",
                i,
                transfer,
            )

        initial_psbt = self.bitcoin_multisig.construct_psbt(
            transfers=[
                Transfer(
                    amount_satoshi=to_satoshi(from_wei(transfer.amount_wei)),
                    recipient_address=transfer.recipient_btc_address,
                )
                for transfer in transfers
            ]
        )
        logger.info("Constructed PSBT: %s", initial_psbt)

        serialized_signed_psbts = self.network.ask(
            question="sign-psbt",
            serialized_psbt=initial_psbt.to_base64(),
        )
        signed_psbts = [PSBT.from_base64(serialized) for serialized in serialized_signed_psbts]
        # TODO: loop while len(signed_psbts) < initial_psbt.threshold_for_self_sign
        # TODO: error handling
        finalized_psbt = self.bitcoin_multisig.combine_and_finalize_psbt(
            initial_psbt=initial_psbt,
            signed_psbts=signed_psbts,
        )
        self.bitcoin_multisig.broadcast_psbt(finalized_psbt)

    def _answer_sign_psbt(self, serialized_psbt):
        # TODO: validation, error handling
        psbt = PSBT.from_base64(serialized_psbt)
        signed_psbt = self.bitcoin_multisig.sign_psbt(psbt)
        return signed_psbt.to_base64()
