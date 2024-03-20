import struct
from datetime import datetime, timedelta

import Pyro5.errors

from eth_account import Account
from eth_account.messages import encode_defunct


def encode_binding_and_timestamp(binding, timestamp):
    return encode_defunct(primitive=binding + struct.pack(">Q", int(timestamp)))


def get_signed_handshake_message(binding, privkey):
    encoded = encode_binding_and_timestamp(binding, datetime.now().timestamp())

    signed_message = Account.sign_message(encoded, privkey)

    return signed_message


def recover_message(content, signature):
    return Account.recover_message(
        content,
        signature=signature,
    )


def initial_challenge(binding, privkey):
    signed_message = get_signed_handshake_message(binding, privkey)

    return {
        "binding": binding.hex(),
        "timestamp": int(datetime.now().timestamp()),
        "hash": signed_message.messageHash.hex(),
        "signature": signed_message.signature.hex(),
    }


def validate_message(data, expected_binding, valid_addresses):
    if data["binding"] != expected_binding.hex():
        raise Pyro5.errors.CommunicationError("Binding does not match")

    if (datetime.fromtimestamp(data["timestamp"]) - datetime.now()) > timedelta(minutes=1):
        raise Pyro5.errors.CommunicationError("Received stale timestamp")

    expected_message = encode_binding_and_timestamp(expected_binding, data["timestamp"])
    recovered = recover_message(expected_message, data["signature"])

    if recovered not in valid_addresses:
        raise Pyro5.errors.SecurityError(
            "Recovered address %r does not match any of the allowed addresses %r",
            recovered,
            valid_addresses,
        )
