import logging
import warnings

import sentry_sdk

logger = logging.getLogger(__name__)


def init_sentry(dsn):
    if not dsn:
        warnings.warn("Sentry DSN not set, Sentry disabled", stacklevel=2)
        return

    logger.info("Initializing Sentry")
    sentry_sdk.init(
        dsn=dsn,
    )
