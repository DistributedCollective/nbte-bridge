from io import BytesIO

from bitcointx.core import (
    CTxIn,
    CTxOut,
    CTxWitness,
    CTxInWitness,
    calculate_transaction_virtual_size,
)
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
