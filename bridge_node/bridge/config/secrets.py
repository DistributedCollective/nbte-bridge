"""
Quick and dirty secrets implementation. We could use the vaults from environ.secrets too...
"""

import json
import logging
import os
import sys
from getpass import getpass
from typing import Any

import environ
from environ._environ_config import RAISE  # noqa

logger = logging.getLogger(__name__)


def wait_for_secrets():
    """
    Wait for the user to provide decrypted secrets as a single-line JSON string.
    In practice, this should be done by running server/serve_with_secrets.py.

    Requires the BRIDGE_ENCRYPTED_SECRETS environment variable to be set to 1.
    """
    try:
        return json.loads(getpass("Provide decrypted secrets: "))
    except json.JSONDecodeError:
        logger.error("Invalid JSON provided for secrets.")
        sys.exit(1)


ENCRYPTED_SECRETS_ENABLED = os.environ.get("BRIDGE_ENCRYPTED_SECRETS", False)


if ENCRYPTED_SECRETS_ENABLED:
    _secrets = wait_for_secrets()
else:
    logging.warning(
        "Encrypted secrets not enabled, proceeding with secrets from environment vars. "
        ""
        "This should not happen in production."
    )
    _secrets = {}


def secret(
    name: str,
    default: Any = RAISE,
) -> Any:
    if ENCRYPTED_SECRETS_ENABLED:
        logger.info("Getting secret %s from secrets file.", name)
        value = _secrets.get(name, default)
        if value is RAISE:
            raise ValueError(f"Secret {name} not found in secrets file.")
    else:
        logger.debug("Falling back to environ for secret %s.", name)
        value = environ.var(default=default)
    return value
