import dataclasses
import math
from typing import TypeVar, Union

from bitcointx.core.key import BIP32Path
from bitcointx.core.script import CScript, standard_multisig_redeem_script
from bitcointx.wallet import CCoinExtKey, CCoinExtPubKey, P2WSHBitcoinAddress
from eth_typing import HexAddress
from eth_utils import is_checksum_address, remove_0x_prefix, to_checksum_address

from bridge.btc.utils import encode_segwit_address

TExtKey = TypeVar("TExtKey", bound=Union[CCoinExtKey, CCoinExtPubKey])


DEPOSIT_ADDRESS_BASE_DERIVATION_PATH = "m/1"
MAX_INDEX = (
    100  # < 2**31. derivation index is 32bit, 31bit+ are reserved for hardened key derivation
)


def get_derivation_path_for_deposit_address(
    evm_address: Union[HexAddress, str],
    index: int,
    *,
    base_derivation_path=DEPOSIT_ADDRESS_BASE_DERIVATION_PATH,
) -> BIP32Path:
    """
    Derive a key that corresponds to the deposit address of a user
    DO NOT MODIFY THE IMPLEMENTATION WITHOUT BEING CAREFUL! This needs to be consistent between all nodes
    for deterministic deposit address generation
    """
    if not is_checksum_address(evm_address):
        raise ValueError(
            f"Invalid evm_address: {evm_address!r} (must be a checksummed, 0x-prefixed EVM address)"
        )
    if index < 0:
        raise ValueError(f"index must be non-negative, got {index}")
    if index > MAX_INDEX:
        raise ValueError(f"index must be less than {MAX_INDEX}, got {index}")

    assert 0 <= index < 2**31  # sanity check for key derivation

    address_bytes = bytes.fromhex(remove_0x_prefix(evm_address))

    num_bytes_per_part = 3
    assert (
        2 ** (num_bytes_per_part * 8) < 2**31
    )  # 31bits + are reserved for hardened key derivation
    num_parts = math.ceil(len(address_bytes) / num_bytes_per_part)
    assert num_parts * num_bytes_per_part >= len(address_bytes)
    parts = []
    for i in range(num_parts):
        start = i * num_bytes_per_part
        end = start + num_bytes_per_part
        parts.append(address_bytes[start:end])

    # Sanity checks to see that the parts correspond to the address
    assert b"".join(parts) == address_bytes
    assert to_checksum_address(b"".join(parts)) == evm_address

    path = BIP32Path(base_derivation_path)
    path += [int.from_bytes(part, "big") for part in parts]
    path += [index]
    return path


def derive_key_for_deposit_address(
    key: TExtKey,
    evm_address: Union[HexAddress, str],
    index: int,
    *,
    base_derivation_path=DEPOSIT_ADDRESS_BASE_DERIVATION_PATH,
) -> TExtKey:
    path = get_derivation_path_for_deposit_address(
        evm_address=evm_address, index=index, base_derivation_path=base_derivation_path
    )
    return key.derive_path(path)


@dataclasses.dataclass()
class DepositAddressInfo:
    redeem_script: CScript
    address_script: P2WSHBitcoinAddress
    btc_deposit_address: str
    derivation_path: BIP32Path
    evm_address: str
    index: int


def derive_deposit_address_info(
    master_xpubs: list[CCoinExtPubKey],
    num_required_signers: int,
    evm_address: Union[HexAddress, str],
    index: int,
    *,
    base_derivation_path=DEPOSIT_ADDRESS_BASE_DERIVATION_PATH,
) -> DepositAddressInfo:
    derivation_path = get_derivation_path_for_deposit_address(
        evm_address=evm_address, index=index, base_derivation_path=base_derivation_path
    )
    child_pubkeys = [xpub.derive_path(derivation_path) for xpub in master_xpubs]
    child_pubkeys.sort()
    redeem_script = standard_multisig_redeem_script(
        total=len(master_xpubs),
        required=num_required_signers,
        pubkeys=child_pubkeys,
    )
    address_script = P2WSHBitcoinAddress.from_redeemScript(redeem_script)
    btc_deposit_address = encode_segwit_address(address_script)
    return DepositAddressInfo(
        redeem_script=redeem_script,
        address_script=address_script,
        btc_deposit_address=btc_deposit_address,
        derivation_path=derivation_path,
        evm_address=evm_address,
        index=index,
    )
