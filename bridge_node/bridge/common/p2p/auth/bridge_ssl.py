import logging
import time
from datetime import datetime
from typing import (
    Callable,
    Protocol,
)

import Pyro5.errors

from . import challenge


logger = logging.getLogger(__name__)


class SecureContext(Protocol):
    def validate_handshake(self, conn, data):
        ...


class SecureContextFactory(Protocol):
    def __call__(
        self,
        *,
        privkey: str,
        fetch_peer_addresses: Callable[[], list[str]],
    ) -> SecureContext:
        ...


class PyroSecureContext:
    def __init__(
        self,
        *,
        privkey: str,
        fetch_peer_addresses: Callable[[], list[str]],
    ):
        self.privkey = privkey
        self.fetch_peer_addresses = fetch_peer_addresses
        self._cached_peer_addresses = None
        self._cached_peer_addresses_timestamp = None
        logger.debug("Enabling SSL for Pyro communication")

        Pyro5.config.SSL = True
        Pyro5.config.SSL_REQUIRECLIENTCERT = True  # enable 2-way ssl
        Pyro5.config.SSL_SERVERCERT = "/srv/bridge_backend/certs/server-cert.pem"
        Pyro5.config.SSL_SERVERKEY = "/srv/bridge_backend/certs/server-key.pem"

        Pyro5.config.SSL_CACERTS = "/srv/bridge_backend/certs/ca-cert.pem"

        Pyro5.config.SSL_CLIENTCERT = "/srv/bridge_backend/certs/client-cert.pem"
        Pyro5.config.SSL_CLIENTKEY = "/srv/bridge_backend/certs/client-key.pem"
        Pyro5.config.LOGWIRE = True
        Pyro5.config.COMMTIMEOUT = 3

    def validate_handshake(self, conn, data):
        binding = conn.sock.get_channel_binding(cb_type="tls-unique")

        challenge.validate_message(data, binding, self.get_peer_addresses())

        logger.debug("Handshake validated successfully from peer")

        signed_message = challenge.get_signed_handshake_message(binding, self.privkey)

        return {
            "binding": binding.hex(),
            "timestamp": int(datetime.now().timestamp()),
            "message": signed_message.messageHash.hex(),
            "signature": signed_message.signature.hex(),
        }

    def get_peer_addresses(self) -> list[str]:
        refetch_interval = 60
        if self._cached_peer_addresses is not None:
            if time.time() - self._cached_peer_addresses_timestamp < refetch_interval:
                return self._cached_peer_addresses

        logger.debug("(Re)fetching peer addresses")
        self._cached_peer_addresses = self.fetch_peer_addresses()
        self._cached_peer_addresses_timestamp = time.time()
        return self._cached_peer_addresses
