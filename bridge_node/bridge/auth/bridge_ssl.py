import logging

import Pyro5.errors

from . import challenge


privkey = "0x9a9a640da1fc0181e43a9ea00b81878f26e1678e3e246b25bd2835783f2be181"


def pyro_validate_handshake(conn, data):
    cert = conn.getpeercert()

    logging.debug("Validating handshake with cert: %s", cert)

    return


class SecureContext:
    def __init__(self, *args, **kwargs):
        ...

    def validate_handshake(self, conn, data):
        ...


class PyroSecureContext:
    def __init__(self, *args, **kwargs):
        logging.debug("Enabling SSL for Pyro communication")

        Pyro5.config.SSL = True
        Pyro5.config.SSL_REQUIRECLIENTCERT = True  # enable 2-way ssl
        Pyro5.config.SSL_SERVERCERT = "/certs/server-cert.pem"
        Pyro5.config.SSL_SERVERKEY = "/certs/server-key.pem"

        Pyro5.config.SSL_CACERTS = "/certs/ca-cert.pem"

        Pyro5.config.SSL_CLIENTCERT = "/certs/client-cert.pem"
        Pyro5.config.SSL_CLIENTKEY = "/certs/client-key.pem"
        Pyro5.config.LOGWIRE = True

    def validate_handshake(self, conn, data):
        binding = conn.sock.get_channel_binding(cb_type="tls-unique")
        logging.debug("Received data on handshake: %s", data)

        challenge.validate_message(
            data,
            binding,
            [
                "0x09dcD91DF9300a81a4b9C85FDd04345C3De58F48",
                "0xA40013a058E70664367c515246F2560B82552ACb",
                "0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a",
            ],
        )

        logging.debug("Handshake validated successfully from peer")

        signed_message = challenge.get_signed_handshake_message(binding, privkey)

        return {
            "message": signed_message.messageHash.hex(),
            "signature": signed_message.signature.hex(),
        }
