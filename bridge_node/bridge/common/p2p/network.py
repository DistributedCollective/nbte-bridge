import logging
import threading
from typing import (
    Any,
    Callable,
    Protocol,
    TypedDict,
)

import Pyro5.api
import Pyro5.errors
from anemic.ioc import (
    Container,
    service,
)

from bridge.common.p2p.auth.bridge_ssl import (
    PyroSecureContext,
    SecureContextFactory,
)
from bridge.config import Config
from .client import BoundPyroProxy
from .messaging import MessageEnvelope

logger = logging.getLogger(__name__)


class Listener(Protocol):
    def __call__(self, msg: MessageEnvelope):
        ...


class Network(Protocol):
    node_id: str

    def is_leader(self) -> bool:
        pass

    def ask(self, question: str, **kwargs: Any) -> list[Any]:
        ...

    def answer_with(self, question: str, callback: Callable[..., Any]):
        ...

    def broadcast(self, msg):
        ...

    def send(self, to, msg):
        ...

    def add_listener(self, listener: Listener):
        ...


class PyroMessageEnvelope(TypedDict):
    sender: str
    message: Any


class PyroNetwork(Network):
    def __init__(
        self,
        *,
        node_id,
        host,
        port,
        peers,
        context_cls: SecureContextFactory = None,
        privkey=None,
        leader_node_id=None,
        fetch_peer_addresses: Callable[[], list[str]] = lambda: [],
    ):
        self.host = host
        self.port = port
        self.node_id = node_id
        self.leader_node_id = leader_node_id
        self.context = None
        self.privkey = privkey
        self.fetch_peer_addresses = fetch_peer_addresses

        self.create_daemon(context_cls)

        self._peers = peers  # list of (node_id, hostname:port) tuples

        if self.node_id is None:
            self.node_id = self.uri.object

        self.listeners = []

        self._answer_callbacks = {}

        self._running = False
        self.start()

    def create_daemon(self, context_cls: SecureContextFactory = None):
        if context_cls is not None:
            self.context = context_cls(
                privkey=self.privkey,
                fetch_peer_addresses=self.fetch_peer_addresses,
            )

        self.daemon = Pyro5.api.Daemon(host=self.host, port=self.port)

        if self.context is not None:
            self.daemon.validateHandshake = self.context.validate_handshake

        # NOTE: this is a URI object, not a str
        self.uri = self.daemon.register(self, self.node_id)

    def is_leader(self) -> bool:
        # Leader is hardcoded in config
        return self.node_id == self.leader_node_id

    def ask(self, question: str, **kwargs: Any):
        logger.debug(
            "Asking question %r from all peers",
            question,
        )
        answers = []
        for peer in self.peers:
            try:
                answer = peer.answer(question, **kwargs)
                if answer is not None:
                    # TODO: proper return type for null answer
                    answers.append(answer)
            except Pyro5.errors.CommunicationError:
                logger.exception("Error asking question %s from peer %s", question, peer)
        return answers

    def broadcast(self, msg: Any):
        logger.debug(
            "Broadcasting msg %r to all peers: %s",
            msg,
            [peer._pyroUri.location for peer in self.peers],
        )
        envelope = PyroMessageEnvelope(
            sender=str(self.uri),
            message=msg,
        )
        for peer in self.peers:
            try:
                peer.receive(envelope)
            except Pyro5.errors.CommunicationError:
                logger.exception("Error sending message to peer %s", peer)

    def send(self, to: str, msg: Any):
        logger.debug("Sending msg %r to peer %s", msg, to)
        envelope = PyroMessageEnvelope(
            sender=str(self.uri),
            message=msg,
        )
        with BoundPyroProxy(to, privkey=self.privkey) as peer:
            peer.receive(envelope)

    @Pyro5.api.expose
    def receive(self, envelope: PyroMessageEnvelope):
        logger.debug("Received message envelope: %s", envelope)

        envelope = MessageEnvelope(
            sender=envelope["sender"],
            message=envelope["message"],
        )
        for listener in self.listeners:
            listener(envelope)

    @Pyro5.api.expose
    def answer(self, question, **kwargs):
        logger.debug("Answering question %r (thread %s)", question, threading.current_thread().name)
        answer_callback = self._answer_callbacks.get(question)
        if answer_callback is None:
            logger.warning("No answer callback for question %r", question)
            return None
        try:
            ret = answer_callback(**kwargs)
        except Exception:
            logger.exception(
                "Error answering question %r (thread %s)", question, threading.current_thread().name
            )
            return None
        return ret

    def answer_with(self, question: str, callback: Callable[..., Any]):
        if question in self._answer_callbacks:
            raise ValueError(f"Question {question} already has a callback")
        self._answer_callbacks[question] = callback

    def add_listener(self, listener):
        self.listeners.append(listener)

        logger.debug("Listener added to network: %s", listener)

    def get_peers(self):
        return [
            BoundPyroProxy(
                self.get_peer_uri(peer, host),
                privkey=self.privkey,
            )
            for peer, host in self._peers
            if peer != self.node_id
        ]

    @property
    def peers(self):
        return self.get_peers()

    def get_peer_uri(self, peer_id, peer_host):
        # NOTE: peer_host includes port
        return f"PYRO:{peer_id}@{peer_host}"

    def get_network_info(self):
        return {
            "node_id": self.node_id,
            "uri": str(self.uri),
            "is_leader": self.is_leader(),
            "peers": {peer._pyroUri.object: self.get_peer_info(peer) for peer in self.peers},
        }

    def get_peer_info(self, peer):
        # Due to how peers are created at the moment, it's not connected
        # until the first call is made
        try:
            peer._pyroBind()
        except Pyro5.errors.CommunicationError:
            return {
                "status": "offline",
                "uri": str(peer._pyroUri),
            }

        info = {
            "status": "offline" if not peer._pyroConnection else "online",
            "uri": str(peer._pyroUri),
        }

        peer._pyroRelease()

        return info

    def start(self):
        if self._running:
            raise RuntimeError("Already running")
        logger.info("Starting Pyro daemon loop")

        def daemon_thread():
            self.daemon.requestLoop(loopCondition=lambda: self._running)

        self._running = True
        self._thread = threading.Thread(target=daemon_thread)
        self._thread.start()
        logger.info("Pyro daemon loop started")

    def stop(self):
        if not self._running:
            return
        logger.info("Stopping Pyro daemon loop")
        self._running = False
        self._thread.join()
        logger.info("Pyro daemon loop stopped")


@service(scope="global", interface_override=Network)
def create_pyro_network(container: Container):
    from ..evm.utils import create_web3

    config = container.get(interface=Config)

    # Federator addresses are used for validating handshakes. The addresses
    # are fetched from a smart contact on an EVM-compatible network.
    # We only support a single contract for now. In the future, it might
    # be necessary to extend this to support multiple contracts.
    # We also create a new Web3 for this instead of getting it from the Container,
    # because we anticipate that we might need multiple Web3 instances in the future.
    web3 = create_web3(config.evm_rpc_url)
    federation_contract = web3.eth.contract(
        address=config.evm_bridge_contract_address,
        abi=[
            {
                "inputs": [],
                "name": "getFederators",
                "outputs": [{"internalType": "address[]", "name": "", "type": "address[]"}],
                "stateMutability": "view",
                "type": "function",
            },
        ],
    )

    network = PyroNetwork(
        node_id=config.node_id,
        host=config.hostname,
        port=config.port,
        peers=config.peers,
        context_cls=PyroSecureContext,
        privkey=config.evm_private_key,
        fetch_peer_addresses=federation_contract.functions.getFederators().call,
        leader_node_id=config.leader_node_id,
    )

    # TODO: VERY UGLY! But we don't want to crash on startup if network not started
    # Should rather start the daemon outside of __init__ and then only broadcast after it's started
    import time

    time.sleep(2)

    network.broadcast(f"{network.uri} joined the network")
    return network
