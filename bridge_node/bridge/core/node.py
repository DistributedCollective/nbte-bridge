import logging
import time
import random

from anemic.ioc import autowired, auto, service, Container

from ..p2p.network import Network
from ..p2p.messaging import MessageEnvelope

from ..evm.scanner import BridgeEventScanner, TransferToBTC
from ..btc.rpc import BitcoinRPC
from ..btc.utils import to_satoshi
from ..evm.utils import from_wei

logger = logging.getLogger(__name__)


@service(scope="global")
class BridgeNode:
    network: Network = autowired(auto)
    evm_scanner: BridgeEventScanner = autowired(auto)
    bitcoin_rpc: BitcoinRPC = autowired(auto)

    def __init__(self, container: Container):
        self.container = container
        self.network.add_listener(self.on_message)

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
        if not random.randint(0, 3):
            # Randomly ping nodes to demonstrate network connectivity
            self.ping()
        events = self.evm_scanner.scan_events()
        for event in events:
            match event:
                case TransferToBTC():
                    self._handle_transfer_to_btc(event)
                case _:
                    logger.info("Found unknown event: %s", event)

    def _handle_transfer_to_btc(self, transfer: TransferToBTC):
        logger.info("Handling transfer to BTC: %s", transfer)
        for _ in range(5):
            logger.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        logger.info(
            "Found transfer to BTC: %s",
            transfer,
        )

        # TODO: temporary code to get the flow working with a single node
        logger.info("My node id is %s", self.network.node_id)
        if self.network.node_id != "rollup-bridge-1":
            logger.info("Not node1, skipping")
            return

        logger.info("Node1, handling transfer")
        amount_btc = from_wei(transfer.amount_wei)
        amount_satoshi = to_satoshi(amount_btc)
        logger.info(
            "Transferring %s BTC (%s satoshi) to %s",
            amount_btc,
            amount_satoshi,
            transfer.recipient_btc_address,
        )
        # balance = self.bitcoin_rpc.getbalance()
        # print("Balance", balance)
        # unspent = self.bitcoin_rpc.listunspent()
        # print("Num utxos", len(unspent))
        result = self.bitcoin_rpc.call(
            "sendtoaddress",
            transfer.recipient_btc_address,
            str(amount_btc),
            "",  # comment
            "",  # commentto
            False,  # subtractfeefromamount
            True,  # replaceable
            None,  # conf_target
            "unset",  # estimate_mode
            False,  # avoid reuse
            1,  # fee_rate (sat/vbyte)
        )
        logger.info("Sent BTC: %s", result)
