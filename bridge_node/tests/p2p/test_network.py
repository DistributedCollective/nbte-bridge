from collections import namedtuple

from bridge.p2p.network import Network, PyroNetwork, PyroMessageEnvelope


class TransportServerStub:
    def __init__(self, *args, **kwargs):
        self.locationStr = "localhost:8080"
        Socket = namedtuple("Socket", ["family"])

        self.sock = Socket(family="family")

    def init(*args, **kwargs):
        pass

    def loop(*args, **kwargs):
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


def test_methods_can_be_exposed_to_pyro_network(mocker):
    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )  # I don't want to actually start a server in an unit test

    network = PyroNetwork(node_id="test", host="localhost", port=8080, peers=[])

    class TestObject:
        def test_method(self):
            return "test"

    test_object = TestObject()

    network.daemon.register(test_object, "test_object")

    assert network.daemon.uriFor(test_object).object == "test_object"


def test_pyro_network_can_broadcast_messages(mocker):
    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )

    peer = PeerStub()
    mocker.patch("Pyro5.api.Proxy", peer)

    # TODO: I don't want to actually start a server in an unit test
    # so I mock the peer.
    # This tests mainly our own code, not Pyro5.
    # Actual integration tests are needed later

    network = PyroNetwork(
        node_id="test", host="localhost", port=8080, peers=[("test2", "localhost:8080")]
    )

    message = "The Abyss returns even the boldest gaze."
    network.broadcast(message)

    assert message in [message["message"] for message in peer.messages]


def test_messages_can_be_delivered_to_listeners(mocker):
    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )

    network = PyroNetwork(node_id="test", host="localhost", port=8080, peers=[])

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
