import logging
import warnings

import sentry_sdk
from Pyro5.errors import CommunicationError, SecurityError

logger = logging.getLogger(__name__)


def init_sentry(dsn):
    if not dsn:
        warnings.warn("Sentry DSN not set, Sentry disabled", stacklevel=2)
        return

    def before_send(event, hint):
        if "exc_info" in hint:
            exc_value = hint["exc_info"][1]

            # TODO: Address recovered from Pyro5 handshake is sometimes not valid. Not sure why this would happen --
            #       it needs to be investigated, but for now let's just ignore
            if isinstance(exc_value, CommunicationError | SecurityError):
                if "does not match any of the allowed addresses" in str(exc_value):
                    logger.info("Ignoring Pyro5 error: %s", exc_value)
                    return None

        return event

    logger.info("Initializing Sentry")
    sentry_sdk.init(
        dsn=dsn,
        before_send=before_send,
    )
