import secrets
from hashlib import scrypt
from typing import Any, Dict, Union

from Crypto.Cipher import AES

SALT_LENGH = 16
NONCE_LENGTH = 12
CIPHER_TAG_LENGTH = 16  # TODO: get this from the lib somehow


def is_encrypted(config: Dict[str, Any]) -> bool:
    return "salt" in config


def encrypt(message: bytes, key: bytes):
    nonce = secrets.token_bytes(NONCE_LENGTH)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(message)
    return nonce + ciphertext + tag


def encrypt_secrets(password: bytes, key_values: Dict[str, str]) -> Dict[str, Any]:
    salt = secrets.token_bytes(SALT_LENGH)
    key = create_key(password, salt=salt)
    return {
        "salt": salt.hex(),
        "encryptedSecrets": {
            k: encrypt(str(v).encode(), key).hex() for (k, v) in key_values.items()
        },
    }


def decrypt(encrypted: bytes, key: bytes):
    nonce = encrypted[:NONCE_LENGTH]
    ciphertext = encrypted[NONCE_LENGTH:-CIPHER_TAG_LENGTH]
    tag = encrypted[-CIPHER_TAG_LENGTH:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    decrypted = cipher.decrypt_and_verify(ciphertext, tag)
    return decrypted.decode()


def decrypt_secrets(
    password: bytes, key_values: Dict[str, Union[str, Dict[str, str]]]
) -> Dict[str, Any]:
    salt = bytes.fromhex(key_values["salt"])
    encrypted_secrets = key_values["encryptedSecrets"]
    key = create_key(password, salt=salt)
    return {k: decrypt(bytes.fromhex(v), key) for (k, v) in encrypted_secrets.items()}


def create_key(password: bytes, salt: bytes) -> bytes:
    return scrypt(password, salt=salt, n=16384, r=8, p=1, dklen=32)
