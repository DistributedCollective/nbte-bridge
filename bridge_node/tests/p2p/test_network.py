from collections import namedtuple

from bridge.p2p.network import P2PNetwork


class TransportServerStub:
    def __init__(self, *args, **kwargs):
        self.locationStr = "localhost:8080"
        Socket = namedtuple("Socket", ["family"])

        self.sock = Socket(family="family")

    def init(*args, **kwargs):
        pass


def test_methods_can_be_exposed_to_network(mocker):
    # I don't want to create sockets for unit tests

    mocker.patch(
        "Pyro5.svr_threads.SocketServer_Threadpool",
        TransportServerStub,
    )

    network = P2PNetwork("localhost", 8080)

    class TestObject:
        def test_method(self):
            return "test"

    test_object = TestObject()

    network.daemon.register(test_object, "test_object")

    assert network.daemon.uriFor(test_object).object == "test_object"


def test_network_can_broadcast_messages(monkeypatch):
    actual_messages = []

    monkeypatch.setattr(P2PNetwork, "receive", lambda message: actual_messages.append(message))

    network = P2PNetwork("localhost", 8080)

    network.broadcast("test")

    assert actual_messages == ["test"]
