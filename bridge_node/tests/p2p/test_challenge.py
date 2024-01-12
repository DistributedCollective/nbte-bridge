from bridge.auth import challenge, bridge_ssl


class SocketStub:
    def get_channel_binding(*args, **kwargs):
        return bytes.fromhex("1234")


class ConnectionStub:
    sock = SocketStub()


def test_challenge_pingpong():
    context = bridge_ssl.PyroSecureContext()

    conn = ConnectionStub()

    context.validate_handshake(conn, challenge.initial_challenge(bytes.fromhex("1234")))
