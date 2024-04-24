import secrets

import bitcointx
from bitcointx.wallet import CCoinExtKey, CCoinExtPubKey


def generate_extended_keypair(seed: bytes = None) -> tuple[CCoinExtKey, CCoinExtPubKey]:
    assert bitcointx.get_current_chain_params().get_network_id() == "regtest"
    if seed is None:
        seed = secrets.token_bytes(64)
    xprv = CCoinExtKey.from_seed(seed)
    xpub = xprv.neuter()
    return xprv, xpub
