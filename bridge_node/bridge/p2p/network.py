from typing import Protocol, Any, TypedDict
import logging
import threading

import Pyro5.api

from .messaging import MessageEnvelope


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


class PyroMessageEnvelope(TypedDict):
    sender: str
    message: Any


class PyroNetwork(Network):
    def __init__(self, *, node_id, host, port):
        self.daemon = Pyro5.api.Daemon(host=host, port=port)
        self.host = host
        self.port = port
        self.node_id = node_id

        # NOTE: this is a URI object, not a str
        self.uri = self.daemon.register(self, self.node_id)

        if self.node_id is None:
            self.node_id = self.uri.object

        self.listeners = []

        self.start()

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
            peer.receive(envelope)

    def send(self, to: str, msg: Any):
        logging.debug("Sending msg %r to peer %s", msg, to)
        envelope = PyroMessageEnvelope(
            sender=str(self.uri),
            message=msg,
        )
        with Pyro5.api.Proxy(to) as peer:
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
        peers = [
            ("rollup-bridge-1", "bridge-node-1"),
            ("rollup-bridge-2", "bridge-node-2"),
            ("rollup-bridge-3", "bridge-node-3"),
        ]

        return [
            Pyro5.api.Proxy(self.get_peer_uri(peer, host))
            for peer, host in peers
            if peer != self.node_id
        ]

    @property
    def peers(self):
        return self.get_peers()

    def get_peer_uri(self, peer_id, peer_host):
        # TODO: should not use self.port here, nodes can have different ports
        return f"PYRO:{peer_id}@{peer_host}:{self.port}"

    def start(self):
        logging.info("Starting Pyro daemon loop")
        self.thread = threading.Thread(target=self.daemon.requestLoop)
        self.thread.start()
