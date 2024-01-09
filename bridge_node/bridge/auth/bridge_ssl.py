import logging

import Pyro5.errors

logger = logging.getLogger(__name__)


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
        logger.debug("Enabling SSL for Pyro communication")

        Pyro5.config.SSL = True
        Pyro5.config.SSL_REQUIRECLIENTCERT = True  # enable 2-way ssl
        Pyro5.config.SSL_SERVERCERT = "/certs/server-cert.pem"
        Pyro5.config.SSL_SERVERKEY = "/certs/server-key.pem"

        Pyro5.config.SSL_CACERTS = "/certs/ca-cert.pem"

        Pyro5.config.SSL_CLIENTCERT = "/certs/client-cert.pem"
        Pyro5.config.SSL_CLIENTKEY = "/certs/client-key.pem"

    def validate_handshake(self, conn, data):
        pass
