import logging
import time

from anemic.ioc import autowired, auto, service, Container

from eth_account.messages import encode_defunct

from ..btc.types import PSBT
from ..evm.contracts import BridgeContract
from ..p2p.network import Network
from ..p2p.messaging import MessageEnvelope

from ..evm.scanner import BridgeEventScanner, TransferToBTC
from ..evm.account import Account
from ..btc.rpc import BitcoinRPC
from ..btc.utils import from_satoshi, to_satoshi
from ..btc.multisig import Transfer, BitcoinMultisig
from ..evm.utils import from_wei, to_wei
from web3 import Web3

logger = logging.getLogger(__name__)


@service(scope="global")
class BridgeNode:
    network: Network = autowired(auto)
    evm_scanner: BridgeEventScanner = autowired(auto)
    evm_account: Account = autowired(auto)
    bitcoin_rpc: BitcoinRPC = autowired(auto)
    bitcoin_multisig: BitcoinMultisig = autowired(auto)
    bridge_contract: BridgeContract = autowired(auto)
    web3: Web3 = autowired(auto)

    def __init__(self, container: Container):
        self.container = container
        self.network.add_listener(self.on_message)
        self.network.answer_with("sign-evm-to-btc-psbt", self._answer_sign_evm_to_btc_psbt)
        self.network.answer_with("sign-btc-to-evm", self._answer_sign_btc_to_evm)

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

        transfers_to_evm = self.bitcoin_multisig.scan_new_deposits()

        if not self.network.is_leader():
            logger.info("Not leader, not doing anything")
            return

        if transfers_to_btc:
            # TODO: should limit max amount of transfers per psbt
            self._handle_transfers_to_btc(transfers_to_btc)

        if transfers_to_evm:
            self._handle_transfers_to_evm(transfers_to_evm)

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
            question="sign-evm-to-btc-psbt",
            serialized_psbt=initial_psbt.to_base64(),
        )
        signed_psbts = [PSBT.from_base64(serialized) for serialized in serialized_signed_psbts]
        signed_psbts.append(self.bitcoin_multisig.sign_psbt(initial_psbt))

        # TODO: loop while len(signed_psbts) < initial_psbt.threshold_for_self_sign
        # TODO: error handling
        finalized_psbt = self.bitcoin_multisig.combine_and_finalize_psbt(
            initial_psbt=initial_psbt,
            signed_psbts=signed_psbts,
        )
        txid = self.bitcoin_multisig.broadcast_psbt(finalized_psbt)
        logger.info("Transaction broadcast, txid %s", txid)

    def _handle_transfers_to_evm(self, transfers):
        logger.info("Handling %s transfers from BTC to EVM", len(transfers))
        for i, transfer in enumerate(transfers):
            logger.info(
                "#%d: %s",
                i,
                transfer,
            )

        for transfer in transfers:
            amount_wei = to_wei(from_satoshi(transfer.amount_satoshi))
            evm_address = transfer.address_info.evm_address
            logger.info("Sending %s wei to %s", amount_wei, evm_address)
            signatures = self.network.ask(
                question="sign-btc-to-evm",
                evm_address=evm_address,
                amount_wei=amount_wei,
                btc_tx_id=transfer.txid,
                btc_tx_vout=transfer.vout,
            )
            logger.info("Got %d signatures", len(signatures))
            # TODO: validate signatures
            # TODO: loop if not enough signatures
            tx_hash = self.bridge_contract.functions.acceptTransferFromBtc(
                evm_address,
                amount_wei,
                "0x" + transfer.txid,
                transfer.vout,
                signatures,
            ).transact()
            logger.info("Tx hash %s, waiting...", tx_hash.hex())
            self.web3.eth.wait_for_transaction_receipt(tx_hash, poll_latency=2)
            logger.info("Tx sent")

    def _answer_sign_evm_to_btc_psbt(self, serialized_psbt):
        # TODO: validation, error handling
        psbt = PSBT.from_base64(serialized_psbt)
        signed_psbt = self.bitcoin_multisig.sign_psbt(psbt)
        return signed_psbt.to_base64()

    def _answer_sign_btc_to_evm(
        self,
        *,
        evm_address: str,
        amount_wei: int,
        btc_tx_id: str,
        btc_tx_vout: int,
    ) -> str:
        if self.bridge_contract.functions.isProcessed(
            "0x" + btc_tx_id,
            btc_tx_vout,
        ):
            raise ValueError("Transfer already processed")
        # TODO: validate that the transfer actually happened
        message_hash = self.bridge_contract.functions.getTransferFromBtcMessageHash(
            evm_address,
            amount_wei,
            "0x" + btc_tx_id,
            btc_tx_vout,
        ).call()
        signable_message = encode_defunct(primitive=message_hash)
        signed_message = self.evm_account.sign_message(signable_message)
        return signed_message.signature.hex()
