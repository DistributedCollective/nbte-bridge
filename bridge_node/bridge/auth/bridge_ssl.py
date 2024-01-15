import logging

import Pyro5.errors

from datetime import datetime

from . import challenge


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
    def __init__(self, privkey, *args, **kwargs):
        self.privkey = privkey
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

        challenge.validate_message(data, binding, self.get_peer_addresses())

        logging.debug("Handshake validated successfully from peer")

        signed_message = challenge.get_signed_handshake_message(binding, self.privkey)

        return {
            "binding": binding.hex(),
            "timestamp": int(datetime.now().timestamp()),
            "message": signed_message.messageHash.hex(),
            "signature": signed_message.signature.hex(),
        }

    def get_peer_addresses(self):  # TODO: get from external service
        return [
            "0x09dcD91DF9300a81a4b9C85FDd04345C3De58F48",
            "0xA40013a058E70664367c515246F2560B82552ACb",
            "0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a",
        ]
