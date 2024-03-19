import dataclasses
import re
from io import BytesIO

from bitcointx.core import (
    CTxIn,
    CTxInWitness,
    CTxOut,
    CTxWitness,
    calculate_transaction_virtual_size,
)
from bitcointx.core.key import (
    BIP32Path,
    CPubKey,
)
from bitcointx.core.psbt import PSBT_KeyDerivationInfo
from bitcointx.core.script import (
    CScript,
    CScriptWitness,
)
from bitcointx.wallet import P2WSHBitcoinAddress


def estimate_p2wsh_multisig_tx_virtual_size(
    *,
    vin: list[CTxIn],
    vout: list[CTxOut],
    num_signatures: int,
    redeem_script: CScript,
    add_change_out: bool = False,
    # TODO: we just assume that each input is a P2WSH input (reasonable for multisigs)
    # AND that the signatures are always 71 bytes (might not be 100% accurate but close enough)
    signature_length_bytes: int = 71,
) -> int:
    """
    Calculate the (estimated) size in vBytes of a possibly-unsigned PSBT for P2WSH transaction
    """
    # Mostly copied from CTransaction.get_virtual_size, but accounts for witness data and change output
    vin = list(vin)
    vout = list(vout)
    if add_change_out:
        vout.append(
            CTxOut(
                nValue=1,
                scriptPubKey=P2WSHBitcoinAddress.from_redeemScript(
                    redeem_script,
                ).to_scriptPubKey(),
            )
        )

    # Input size calculation
    f = BytesIO()
    for txin in vin:
        txin.stream_serialize(f)
    inputs_size = len(f.getbuffer())

    # Output size calculation
    f = BytesIO()
    for txout in vout:
        txout.stream_serialize(f)
    outputs_size = len(f.getbuffer())

    # Witness size calculation
    vtxinwit = []
    for _ in vin:
        vtxinwit.append(
            CTxInWitness(
                CScriptWitness(
                    stack=[
                        b"",
                        *(b"\x00" * signature_length_bytes for _ in range(num_signatures)),
                        redeem_script,
                    ]
                )
            ),
        )
    wit = CTxWitness(vtxinwit)
    if wit.is_null():
        witness_size = 0
    else:
        f = BytesIO()
        wit.stream_serialize(f)
        witness_size = len(f.getbuffer())

    return calculate_transaction_virtual_size(
        num_inputs=len(vin),
        inputs_serialized_size=inputs_size,
        num_outputs=len(vout),
        outputs_serialized_size=outputs_size,
        witness_size=witness_size,
    )


@dataclasses.dataclass
class DescriptorParseResult:
    num_required_signers: int
    num_signers: int
    derivation_map: dict[CPubKey, PSBT_KeyDerivationInfo]
    master_fingerprints: set[bytes]


def parse_p2wsh_multisig_utxo_descriptor(
    descriptor: str,
) -> DescriptorParseResult:
    """
    Parse a from a P2WSH multisig descriptor for a single UTXO
    (i.e. the 'desc' field of each object returned by listunspent).

    The descriptor looks like this (without newlines):

        wsh(multi(1,[7f3e784c/0/0/0]02557f9ba4873a6241dab9800cb16a09f0a1017b993aa26722e743309ef22bce6c,
        [8895ce69/0/0/0]03575ea3a4be64cddefaa78d0f106dad02699545a508fd92f0ee8ecba635b5d708))#kxmewpkl

    The returned object contains a derivation map (suitable for adding to PSBT_Input),
    as well as data suitable for additional validation.
    """
    derivation_map = {}
    master_fingerprints = set()

    match = re.match(
        r"^wsh\(multi\((\d+),((?:\[.*?\][a-f0-9]+,?)+)\)\)#[a-z0-9]+$",
        descriptor,
    )
    if not match:
        raise ValueError(f"Descriptor doesn't look like p2wsh multisig: {descriptor!r}")

    num_required_signers = int(match.group(1))

    pubkey_derivation_infos = match.group(2).split(",")
    num_signers = len(pubkey_derivation_infos)

    for pubkey_derivation_info in pubkey_derivation_infos:
        match = re.match(r"^\[([a-z0-f]+)/(.*)\]([a-f0-9]+)$", pubkey_derivation_info)
        if not match:
            raise ValueError(f"Invalid pubkey derivation info: {pubkey_derivation_info!r}")
        master_fingerprint_hex, derivation_path, pubkey_hex = match.groups()
        master_fingerprint = bytes.fromhex(master_fingerprint_hex)
        master_fingerprints.add(master_fingerprint)
        derivation_map[CPubKey.fromhex(pubkey_hex)] = PSBT_KeyDerivationInfo(
            master_fp=master_fingerprint, path=BIP32Path(f"m/{derivation_path}")
        )

    return DescriptorParseResult(
        num_required_signers=num_required_signers,
        num_signers=num_signers,
        derivation_map=derivation_map,
        master_fingerprints=master_fingerprints,
    )
