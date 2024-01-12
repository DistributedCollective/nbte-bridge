from typing import Protocol, Any, TypedDict
import logging
import threading

import Pyro5.api
import Pyro5.errors

from anemic.ioc import Container, service
from .messaging import MessageEnvelope

from ..auth import challenge
from ..auth.bridge_ssl import SecureContext, PyroSecureContext

from ..config import Config

from .client import Proxy


class Listener(Protocol):
    def __call__(self, msg: MessageEnvelope):
        ...


class Network(Protocol):
    node_id: str

    def broadcast(self, msg):
        ...

    def send(self, to, msg):
        ...

    def add_listener(self, listener: Listener):
        ...


class BoundPyroProxy(Proxy):
    def _pyroValidateHandshake(self, response):
        logging.debug("Validating handshake on client, response: %s", response)
        challenge.validate_message(
            response,
            self._pyroConnection.sock.get_channel_binding(cb_type="tls-unique"),
            [
                "0x09dcD91DF9300a81a4b9C85FDd04345C3De58F48",
                "0xA40013a058E70664367c515246F2560B82552ACb",
                "0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a",
            ],
        )

        logging.debug("Handshake validated")

        return


class PyroMessageEnvelope(TypedDict):
    sender: str
    message: Any


class PyroNetwork(Network):
    def __init__(self, *, node_id, host, port, peers, context_cls: SecureContext = None):
        self.host = host
        self.port = port
        self.node_id = node_id
        self.context = None

        self.create_daemon(context_cls)

        self._peers = peers  # list of (node_id, hostname:port) tuples

        if self.node_id is None:
            self.node_id = self.uri.object

        self.listeners = []

        self.start()

    def create_daemon(self, context_cls: SecureContext | Any = None):
        if context_cls is not None:
            self.context = context_cls()

        self.daemon = Pyro5.api.Daemon(host=self.host, port=self.port)

        if self.context is not None:
            self.daemon.validateHandshake = self.context.validate_handshake

        # NOTE: this is a URI object, not a str
        self.uri = self.daemon.register(self, self.node_id)

    def broadcast(self, msg: Any):
        logging.debug(
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
                logging.exception("Error sending message to peer %s", peer)

    def send(self, to: str, msg: Any):
        logging.debug("Sending msg %r to peer %s", msg, to)
        envelope = PyroMessageEnvelope(
            sender=str(self.uri),
            message=msg,
        )
        with BoundPyroProxy(to) as peer:
            peer.receive(envelope)

    @Pyro5.api.expose
    def receive(self, envelope: PyroMessageEnvelope):
        logging.debug("Received message envelope: %s", envelope)

        envelope = MessageEnvelope(
            sender=envelope["sender"],
            message=envelope["message"],
        )
        for listener in self.listeners:
            listener(envelope)

    def add_listener(self, listener):
        self.listeners.append(listener)

        logging.debug("Listener added to network: %s", listener)

    def get_peers(self):
        return [
            BoundPyroProxy(
                self.get_peer_uri(peer, host),
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

    def start(self):
        logging.info("Starting Pyro daemon loop")
        self.thread = threading.Thread(target=self.daemon.requestLoop)
        self.thread.start()


@service(scope="global", interface_override=Network)
def create_pyro_network(container: Container):
    config = container.get(interface=Config)
    network = PyroNetwork(
        node_id=config.node_id,
        host=config.hostname,
        port=config.port,
        peers=config.peers,
        context_cls=PyroSecureContext,
    )

    # TODO: VERY UGLY! But we don't want to crash on startup if network not started
    # Should rather start the daemon outside of __init__ and then only broadcast after it's started
    import time

    time.sleep(2)

    network.broadcast(f"{network.uri} joined the network")
    return network
