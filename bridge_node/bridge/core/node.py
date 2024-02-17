import logging
import time

from anemic.ioc import Container, auto, autowired, service
from eth_account.messages import encode_defunct
from eth_utils import add_0x_prefix
from web3 import Web3

from bridge.common.services.transactions import TransactionManager
from bridge.common.evm.account import Account
from bridge.common.evm.contracts import BridgeContract
from bridge.common.evm.scanner import BridgeEventScanner, TransferToTap
from bridge.common.p2p.messaging import MessageEnvelope
from bridge.common.p2p.network import Network
from bridge.common.tap.client import TapRestClient
from bridge.common.tap.deposits import TapDeposit, TapDepositService

logger = logging.getLogger(__name__)


@service(scope="global")
class BridgeNode:
    network: Network = autowired(auto)
    transaction_manager: TransactionManager = autowired(auto)
    evm_account: Account = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    web3: Web3 = autowired(auto)
    tap_client: TapRestClient = autowired(auto)

    def __init__(self, container: Container):
        self.container = container
        self.network.add_listener(self.on_message)
        self.network.answer_with("sign-evm-to-tap", self._answer_sign_evm_to_tap)
        self.network.answer_with("sign-tap-to-evm", self._answer_sign_tap_to_evm)

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
        with self.transaction_manager.transaction() as transaction:
            evm_scanner = transaction.find_service(BridgeEventScanner)
            tap_deposit_service = transaction.find_service(TapDepositService)

            events = evm_scanner.scan_events()
            transfers_to_tap: list[TransferToTap] = []
            for event in events:
                match event:
                    case TransferToTap():
                        transfers_to_tap.append(event)
                    case _:
                        logger.info("Found unknown event: %s", event)

            transfers_from_tap = tap_deposit_service.scan_new_deposits()

        if not self.network.is_leader():
            logger.info("Not leader, not doing anything")
            return

        if transfers_to_tap:
            # TODO: should limit max amount of transfers per psbt
            self._handle_transfers_to_tap(transfers_to_tap)

        if transfers_from_tap:
            self._handle_transfers_from_tap(transfers_from_tap)

    def _handle_transfers_to_tap(self, transfers: list[TransferToTap]):
        logger.info("Handling %s transfers to Tap", len(transfers))
        for i, transfer in enumerate(transfers):
            logger.info(
                "#%d: %s",
                i,
                transfer,
            )

        # TODO: proper VPSBT handling with proof transfers
        ret = self.tap_client.send_assets(
            *[
                t.recipient_tap_address
                for t in transfers
            ]
        )
        logger.info("Transaction broadcast: %s", ret)

    def _handle_transfers_from_tap(self, transfers: list[TapDeposit]):
        logger.info("Handling %s transfers from Tap to EVM", len(transfers))
        for i, transfer in enumerate(transfers):
            logger.info(
                "#%d: %s",
                i,
                transfer,
            )

        for transfer in transfers:
            if self.bridge_contract.functions.isProcessed(
                "0x" + transfer.btc_tx_id,
                transfer.btc_tx_vout,
            ).call():
                logger.warning(
                    "Transfer %s already processed,skipping",
                    transfer,
                )
                continue

            signatures = self.network.ask(
                question="sign-tap-to-evm",
                receiver_rsk_address=transfer.receiver_rsk_address,
                deposit_tap_address=transfer.deposit_tap_address,
                btc_tx_id=transfer.btc_tx_id,
                btc_tx_vout=transfer.btc_tx_vout,
            )
            logger.info("Got %d signatures", len(signatures))
            tx_hash = self.bridge_contract.functions.acceptTransferFromTap(
                transfer.receiver_rsk_address,
                transfer.deposit_tap_address,
                add_0x_prefix(transfer.btc_tx_id),
                transfer.btc_tx_vout,
                signatures,
            ).transact({
                'gas': 20_000_000,
            })
            logger.info("Tx hash %s, waiting...", tx_hash.hex())
            self.web3.eth.wait_for_transaction_receipt(tx_hash, poll_latency=2)
            logger.info("Tx sent")

    def _answer_sign_tap_to_evm(
        self,
        *,
        receiver_rsk_address: str,
        deposit_tap_address: str,
        btc_tx_id: str,
        btc_tx_vout: int,
    ) -> str:
        if self.bridge_contract.functions.isProcessed(
            add_0x_prefix(btc_tx_id),
            btc_tx_vout,
        ).call():
            raise ValueError("Transfer already processed")
        # TODO: more validation
        message_hash = self.bridge_contract.functions.getTransferFromTapMessageHash(
            receiver_rsk_address,
            deposit_tap_address,
            add_0x_prefix(btc_tx_id),
            btc_tx_vout,
        ).call()
        signable_message = encode_defunct(primitive=message_hash)
        signed_message = self.evm_account.sign_message(signable_message)
        return signed_message.signature.hex()

    def _answer_sign_evm_to_tap(
        self,
    ):
        """No-op for now"""

