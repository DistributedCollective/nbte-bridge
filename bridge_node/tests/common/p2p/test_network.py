import dataclasses
from collections import namedtuple
from decimal import Decimal

import pytest

import Pyro5

from bridge.common.p2p.network import Network, PyroNetwork, PyroMessageEnvelope
from bridge.common.p2p.auth.bridge_ssl import PyroSecureContext
from tests.mock_network import MockNetwork


def create_test_pyro_network(node_id="test", host="localhost", port=8080, peers=None):
    return PyroNetwork(node_id=node_id, host=host, port=port, peers=peers or [])


@pytest.fixture
def test_pyro_network(mocker):
    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )  # I don't want to actually start a server in an unit test

    return create_test_pyro_network()


@pytest.fixture
def test_secure_pyro_network(mocker):
    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )  # I don't want to actually start a server in an unit test

    return PyroNetwork(
        node_id="test",
        host="localhost",
        port=8080,
        peers=[],
        context_cls=PyroSecureContext,
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

    # Use a stub context, so we can check if it was called
    network = PyroNetwork(
        node_id="test",
        host="localhost",
        port=8080,
        peers=[],
        context_cls=SecureContextStub,
    )

    assert (
        network.daemon.validateHandshake.__qualname__
        == SecureContextStub.validate_handshake.__qualname__
    )


def test_mock_network():
    network_alice = MockNetwork(node_id="alice")
    network_bob = MockNetwork(node_id="bob")
    network_carol = MockNetwork(node_id="carol")

    network_alice.add_peers([network_bob, network_carol])
    network_bob.add_peers([network_alice, network_carol])
    network_carol.add_peers([network_alice, network_bob])

    networks = [network_alice, network_bob, network_carol]

    for network in networks:
        network.answer_with("test", lambda: "test answer")

    for network in networks:
        assert network.ask("test") == ["test answer", "test answer"]


def test_network_peer_statuses_can_be_listed(test_pyro_network):
    peer1 = ("peer1", "localhost:8081")
    peer2 = ("peer2", "localhost:8082")

    test_pyro_network._peers = [peer1, peer2]

    assert test_pyro_network.get_network_info() == {
        "node_id": "test",
        "uri": "PYRO:test@localhost:8080",
        "is_leader": False,
        "peers": {
            "peer1": {
                "status": "offline",
                "uri": "PYRO:peer1@localhost:8081",
            },
            "peer2": {
                "status": "offline",
                "uri": "PYRO:peer2@localhost:8082",
            },
        },
    }


@dataclasses.dataclass
class SomeQuestion:
    question: int


@dataclasses.dataclass
class NestedQuestion:
    child: SomeQuestion


@dataclasses.dataclass
class SomeAnswer:
    answer: int


def test_ask_answer(mocker, request):
    # PyroSecureContext does global stuff so let's just disable it for now
    mocker.patch(
        "Pyro5.config.SSL",
        False,
    )

    # yeah, here we'll just start some servers
    peer1 = create_test_pyro_network(
        node_id="peer1", host="localhost", port=18081, peers=[("peer2", "localhost:18082")]
    )
    request.addfinalizer(peer1.stop)

    peer2 = create_test_pyro_network(
        node_id="peer2", host="localhost", port=18082, peers=[("peer1", "localhost:18081")]
    )
    request.addfinalizer(peer2.stop)

    peer2.answer_with("test", lambda: "test answer")
    answers = peer1.ask("test")
    assert answers == ["test answer"]

    # Test that it "supports" dataclasses (we actually get SimpleNamespaces for now)
    peer2.answer_with("test_dataclass_1", lambda num: SomeAnswer(answer=num))
    answers = peer1.ask("test_dataclass_1", num=123)
    assert len(answers) == 1
    assert answers[0].answer == 123

    peer2.answer_with("test_dataclass_2", lambda dc: dc.question)
    answers = peer1.ask("test_dataclass_2", dc=SomeQuestion(question=456))
    assert answers == [456]

    peer2.answer_with(
        "test_dataclass_nested", lambda thing: SomeAnswer(answer=thing.child.question)
    )
    answers = peer1.ask(
        "test_dataclass_nested", thing=NestedQuestion(child=SomeQuestion(question=789))
    )
    assert len(answers) == 1
    assert answers[0].answer == 789

    peer2.answer_with("test_decimal", lambda thing: Decimal(2) + thing)
    answers = peer1.ask("test_decimal", thing=Decimal(1))
    assert answers == [Decimal(3)]
