from collections import namedtuple

import pytest

import Pyro5

from bridge.common.p2p.network import Network, PyroNetwork, PyroMessageEnvelope
from bridge.common.p2p.auth.bridge_ssl import PyroSecureContext


@pytest.fixture
def test_pyro_network(mocker):
    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )  # I don't want to actually start a server in an unit test

    return PyroNetwork(node_id="test", host="localhost", port=8080, peers=[])


@pytest.fixture
def test_secure_pyro_network(mocker):
    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )  # I don't want to actually start a server in an unit test

    return PyroNetwork(
        node_id="test", host="localhost", port=8080, peers=[], context_cls=PyroSecureContext
    )


class SecureContextStub:
    def __init__(self, *args, **kwargs):
        self.validated = False
        pass

    def validate_handshake(self, conn, data):
        self.validated = True
        return "Shake it, baby!"


class TransportServerStub:
    def __init__(self, *args, **kwargs):
        self.locationStr = "localhost:8080"
        Socket = namedtuple("Socket", ["family"])

        self.sock = Socket(family="family")

    def init(*args, **kwargs):
        pass

    def loop(*args, **kwargs):
        pass

    def close(*args, **kwargs):
        pass


class PeerStub:
    def __init__(self, *args, **kwargs):
        self.messages = []

        PyroUri = namedtuple("PyroUri", ["object", "location"])
        self._pyroUri = PyroUri(object="test", location="peerstub:none")

    def __call__(self, *args, **kwargs):
        return self

    def receive(self, msg):
        self.messages.append(msg)

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        pass


def test_abstract_network_class_can_be_inherited():
    class TestNetwork(Network):
        def __init__(self, *, node_id, host, port):
            pass

        def broadcast(self, msg):
            pass

        def add_listener(self, listener):
            pass

        def receive(self, msg):
            pass

    network = TestNetwork(
        node_id="test",
        host="localhost",
        port=8080,
    )

    assert network is not None


def test_methods_can_be_exposed_to_pyro_network(test_pyro_network):
    class TestObject:
        def test_method(self):
            return "test"

    test_object = TestObject()

    test_pyro_network.daemon.register(test_object, "test_object")

    assert test_pyro_network.daemon.uriFor(test_object).object == "test_object"


def test_pyro_network_can_broadcast_messages(mocker, test_pyro_network):
    peer = PeerStub()
    mocker.patch("bridge.common.p2p.network.BoundPyroProxy", peer)

    # TODO: I don't want to actually start a server in an unit test
    # so I mock the peer.
    # This tests mainly our own code, not Pyro5.
    # Actual integration tests are needed later

    network = test_pyro_network
    network._peers = [("test2", "localhost:8080")]

    message = "The Abyss returns even the boldest gaze."
    network.broadcast(message)

    assert message in [message["message"] for message in peer.messages]


def test_pyro_network_can_send_messages(mocker, test_pyro_network):
    peer = PeerStub()
    mocker.patch("bridge.common.p2p.network.BoundPyroProxy", peer)

    network = test_pyro_network
    network._peers = [("test2", "localhost:8080")]

    message = "The Abyss returns even the boldest gaze."
    network.send(peer, message)

    assert message in [message["message"] for message in peer.messages]


def test_messages_can_be_delivered_to_listeners(mocker, test_pyro_network):
    network = test_pyro_network

    expected_message = "The Abyss returns even the boldest gaze."

    envelope = PyroMessageEnvelope(message=expected_message, sender="test_peer")

    class TestClass:
        called = False

        def on_message(self, msg):
            self.called = True
            assert msg.message == expected_message
            assert msg.sender == "test_peer"

    test_object = TestClass()

    network.add_listener(test_object.on_message)
    network.receive(envelope)

    assert test_object.called


def test_ssl_is_enabled_for_pyro_when_using_pyro_secure_context(test_pyro_network):
    context_cls = PyroSecureContext

    network = test_pyro_network

    assert not Pyro5.config.SSL

    network.daemon.unregister(network)
    network.daemon.close()

    network.create_daemon(context_cls=context_cls)

    assert Pyro5.config.SSL is True


def test_custom_handshake_is_used_when_using_a_custom_context(mocker):
    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )

    # Use a stub context so we can check if it was called
    network = PyroNetwork(
        node_id="test", host="localhost", port=8080, peers=[], context_cls=SecureContextStub
    )

    assert (
        network.daemon.validateHandshake.__qualname__
        == SecureContextStub.validate_handshake.__qualname__
    )
