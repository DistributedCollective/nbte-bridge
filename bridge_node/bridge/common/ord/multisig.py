import binascii
import logging
from collections import defaultdict
from io import BytesIO

import pyord
from bitcointx.core import (
    CTransaction,
    CTxIn,
    CTxOut,
)
from bitcointx.core.key import (
    BIP32PathTemplate,
    KeyStore,
)
from bitcointx.core.psbt import (
    PSBT_Input,
    PSBT_Output,
    PartiallySignedTransaction as PSBT,
)
from bitcointx.core.script import (
    CScript,
    standard_multisig_redeem_script,
)
from bitcointx.wallet import (
    CCoinExtKey,
    CCoinExtPubKey,
    P2WSHBitcoinAddress,
)

from .client import OrdApiClient
from .transfers import (
    RuneTransfer,
    TARGET_POSTAGE_SAT,
)
from .utxos import OrdOutputCache
from ..btc import descriptors
from ..btc.multisig_utils import (
    estimate_p2wsh_multisig_tx_virtual_size,
    parse_p2wsh_multisig_utxo_descriptor,
)
from ..btc.rpc import BitcoinRPC
from ..btc.types import UTXO
from ..btc.utils import encode_segwit_address

logger = logging.getLogger(__name__)


class OrdMultisig:
    signer_xpub: str

    def __init__(
        self,
        *,
        master_xpriv: str,
        master_xpubs: list[str],
        num_required_signers: int,
        base_derivation_path: str,
        bitcoin_rpc: BitcoinRPC,
        ord_client: OrdApiClient,
    ):
        _xprv = CCoinExtKey(master_xpriv)
        self._get_master_xpriv = lambda: _xprv
        self._master_xpubs = [CCoinExtPubKey(xpub) for xpub in master_xpubs]
        if _xprv.neuter() not in self._master_xpubs:
            raise ValueError("master_xpriv not in master_xpubs")
        self.signer_xpub = str(_xprv.neuter())

        self._num_required_signers = num_required_signers

        if not base_derivation_path.startswith("m"):
            raise ValueError("base_derivation_path must start with 'm'")
        self._base_derivation_path = base_derivation_path
        self._ranged_derivation_path = base_derivation_path + "/*"
        # self._key_derivation_path = base_derivation_path + '/0'

        self._multisig_redeem_script = self._derive_redeem_script(0)
        self._multisig_script = P2WSHBitcoinAddress.from_redeemScript(self._multisig_redeem_script)
        self._multisig_address = encode_segwit_address(self._multisig_script)

        self._bitcoin_rpc = bitcoin_rpc

        self._ord_client = ord_client
        self._ord_output_cache = OrdOutputCache(
            ord_client=ord_client,
        )

    @property
    def change_address(self):
        return self._multisig_address

    @property
    def num_required_signers(self) -> int:
        return self._num_required_signers

    def get_descriptor(self):
        return self._get_descriptor(self._master_xpubs)

    def _get_descriptor_with_xprv(self):
        keys = self._master_xpubs[:]
        xprv = self._get_master_xpriv()
        wallet_xpub_index = keys.index(xprv.neuter())
        keys[wallet_xpub_index] = xprv
        return self._get_descriptor(keys)

    def _get_descriptor(self, keys):
        required = self._num_required_signers
        ranged_derivation_path = self._ranged_derivation_path
        keys_str = ",".join(
            ranged_derivation_path.replace(
                "m",
                str(key),
            )
            for key in keys
        )
        descriptor = f"wsh(sortedmulti({required},{keys_str}))"
        return descriptors.descsum_create(descriptor)

    def import_descriptors_to_bitcoind(
        self,
        *,
        timestamp="now",
        range: int | tuple[int, int],
    ):
        response = self._bitcoin_rpc.call(
            "importdescriptors",
            [
                {
                    # We don't need to import descriptors with xprv since we're using keystore
                    # "desc": self._get_descriptor_with_xprv(),
                    "desc": self.get_descriptor(),
                    "timestamp": timestamp,
                    "range": range,
                }
            ],
        )
        for result in response:
            if not result.get("success"):
                raise ValueError(f"Failed to import descriptor: {response}")

    def get_rune_balance(self, rune_name: str) -> int:
        utxos = self._list_utxos()
        return sum(
            self._ord_output_cache.get_ord_output(
                txid=utxo.txid,
                vout=utxo.vout,
            ).get_rune_balance(rune_name)
            for utxo in utxos
        )

    def get_rune_balance_at_output(self, *, txid: str, vout: int, rune_name: str) -> int:
        return self._ord_output_cache.get_ord_output(
            txid=txid,
            vout=vout,
        ).get_rune_balance(rune_name)

    def send_runes(self, transfers: list[RuneTransfer]):
        if self._num_required_signers != 1:
            raise ValueError(
                "send_runes can only be used with a 1-of-m multisig",
            )
        psbt = self.create_rune_psbt(transfers)
        signed_psbt = self.sign_psbt(psbt, finalize=True)
        return self.broadcast_psbt(signed_psbt)

    def create_rune_psbt(self, transfers: list[RuneTransfer]):
        # TODO: estimate the sat per vb feerate
        fee_rate_sat_per_vbyte = 50

        # We always have a change output, and we always have it at index 1
        # The first output (index 0) is the Runestone OP_RETURN
        # Change from runes goes to the first non-OP_RETURN output so having this
        # at index 1 makes sense.
        rune_change_output_index = 1
        first_rune_output_index = 2

        required_rune_amounts = defaultdict(int)
        edicts: list[pyord.Edict] = []
        rune_outputs = []

        # Rune outputs and edicts
        for output_index, transfer in enumerate(transfers, start=first_rune_output_index):
            transfer.assert_valid()
            rune_response = self._ord_client.get_rune(transfer.rune.name)
            if not rune_response:
                raise LookupError(f"Rune {transfer.rune} not found (transfer {transfer})")
            rune_id = pyord.RuneId.from_str(rune_response["id"])
            edicts.append(
                pyord.Edict(
                    id=rune_id,
                    amount=transfer.amount,
                    output=output_index,  # receiver is first output
                )
            )
            rune_outputs.append(
                CTxOut(
                    nValue=transfer.postage,
                    scriptPubKey=transfer.get_receiver_script_pubkey(),
                )
            )
            required_rune_amounts[transfer.rune.name] += transfer.amount

        assert all(v > 0 for v in required_rune_amounts.values())

        # Init PSBT with outputs
        psbt = PSBT()
        runestone = pyord.Runestone(
            edicts=edicts,
            pointer=rune_change_output_index,
        )
        # Runestone always goes to output 0
        psbt.add_output(
            txout=CTxOut(
                nValue=0,
                scriptPubKey=CScript(runestone.encipher()),
            ),
            outp=PSBT_Output(
                index=0,
            ),
        )
        # This ist the rune_change_output at index 1
        # We always add a 10 000 sat empty output for rune change
        # TODO: this is not ideal if we don't get change in runes
        psbt.add_output(
            txout=CTxOut(
                nValue=TARGET_POSTAGE_SAT,
                scriptPubKey=self._multisig_script.to_scriptPubKey(),
            ),
            outp=PSBT_Output(
                index=rune_change_output_index,
            ),
        )
        for txout in rune_outputs:
            psbt.add_output(
                txout=txout,
                outp=PSBT_Output(),
            )

        # Coin selection
        utxos = self._list_utxos()
        used_runes = tuple(required_rune_amounts.keys())
        required_rune_amounts = dict(required_rune_amounts)  # no defaultdict anymore
        input_amount_sat = 0

        def add_psbt_input(utxo: UTXO):
            input_tx_response = self._bitcoin_rpc.gettransaction(utxo.txid, True)
            input_tx = CTransaction.stream_deserialize(
                BytesIO(binascii.unhexlify(input_tx_response["hex"])),
            )

            parsed_descriptor = parse_p2wsh_multisig_utxo_descriptor(utxo.desc)
            if self._get_master_xpriv().fingerprint not in parsed_descriptor.master_fingerprints:
                # This should essentially never happen unless other descriptors are imported
                # to the wallet
                raise ValueError(
                    "UTXO doesn't belong to this multisig (master fingerprint not found)"
                )

            psbt.add_input(
                txin=CTxIn(
                    prevout=utxo.outpoint,
                ),
                inp=PSBT_Input(
                    # witness_script=self._multisig_redeem_script,
                    witness_script=utxo.witness_script,
                    utxo=input_tx.vout[utxo.vout],
                    force_witness_utxo=True,
                    derivation_map=parsed_descriptor.derivation_map,
                ),
            )

        # Coin selection for runes
        for utxo in utxos:
            if not utxo.witness_script:
                logger.warning("UTXO doesn't have witnessScript, cannot use: %s", utxo)
                continue
            ord_output = self._ord_output_cache.get_ord_output(
                txid=utxo.txid,
                vout=utxo.vout,
            )
            if not ord_output.has_ord_balances():
                # Not usable for runes
                continue
            if ord_output.inscriptions:
                logger.warning(
                    "UTXO %s (ord output %s) has inscriptions, not using it",
                    utxos,
                    ord_output,
                )
                continue

            relevant_rune_balances_in_utxo = {
                rune: ord_output.get_rune_balance(rune) for rune in used_runes
            }
            if not any(relevant_rune_balances_in_utxo.values()):
                # No runes in this UTXO
                continue

            # This UTXO is selected
            input_amount_sat += utxo.amount_satoshi
            for rune, utxo_balance in relevant_rune_balances_in_utxo.items():
                required_rune_amounts[rune] -= utxo_balance

            add_psbt_input(utxo)

            if all(v <= 0 for v in required_rune_amounts.values()):
                # We have enough runes
                # Change is handled automatically by the protocol as long as the
                # default output in the Runestone is set correctly
                break
        else:
            raise ValueError(
                f"Missing required rune balances: {required_rune_amounts}",
            )

        # Coin selection for funding tx fee
        output_amount_sat = sum(txout.nValue for txout in psbt.unsigned_tx.vout)
        # Change must be either 0 (no output generated) or at least this,
        # else it gets rejected as dust
        min_change_output_value_sat = TARGET_POSTAGE_SAT

        while True:
            tx_size_vbyte = estimate_p2wsh_multisig_tx_virtual_size(
                vin=psbt.unsigned_tx.vin,
                vout=psbt.unsigned_tx.vout,
                num_signatures=self._num_required_signers,
                redeem_script=self._multisig_redeem_script,
                add_change_out=True,
            )
            fee_sat = tx_size_vbyte * fee_rate_sat_per_vbyte
            if input_amount_sat == output_amount_sat + fee_sat:
                # no change output required
                break
            if input_amount_sat >= output_amount_sat + fee_sat + min_change_output_value_sat:
                # change output required
                break

            # Get the next utxo that doesn't have ord balances
            # If no more utxos found, we cannot fund the PSBT
            try:
                while True:
                    utxo = utxos.pop(0)
                    ord_output = self._ord_output_cache.get_ord_output(
                        txid=utxo.txid,
                        vout=utxo.vout,
                    )
                    if not ord_output.has_ord_balances():
                        break
            except IndexError:
                raise ValueError("Don't have enough BTC to fund PSBT")
            if not utxo.witness_script:
                logger.warning("UTXO doesn't have witnessScript, cannot use: %s", utxo)
                continue

            # Add input
            input_amount_sat += utxo.amount_satoshi
            add_psbt_input(utxo)

            # Loop from the start

        # Assuming we got here, TX is funded properly.
        # Add a change output if necessary
        # We add a change output for btc that's separate from the "rune change output"
        change_amount_sat = input_amount_sat - output_amount_sat - fee_sat
        assert change_amount_sat >= 0
        if change_amount_sat > 0:
            psbt.add_output(
                txout=CTxOut(
                    nValue=change_amount_sat,
                    scriptPubKey=self._multisig_script.to_scriptPubKey(),
                ),
                outp=PSBT_Output(),
            )
        assert psbt.get_fee() == fee_sat
        return psbt

    # TODO: add rune-PSBT-specific logic and methods, maybe

    def sign_psbt(self, psbt: PSBT, *, finalize: bool = False) -> PSBT:
        # Keystore works as long as the derivation infos are set for each PSBT input
        psbt = psbt.clone()
        keystore = KeyStore.from_iterable(
            [
                self._get_master_xpriv(),
            ],
            default_path_template=BIP32PathTemplate(self._ranged_derivation_path),
            require_path_templates=True,
        )
        result = psbt.sign(keystore, finalize=finalize)
        assert result.num_inputs_signed == len(psbt.inputs)
        return psbt

        # Alternatively, we could use walletprocesspsbt, which works as long
        # as the descriptor is imported to bitcoind with xpriv:
        # serialized = psbt.to_base64()
        # result = self._bitcoin_rpc.call("walletprocesspsbt", serialized)
        # signed_psbt = PSBT.from_base64(result["psbt"])
        # if finalize:
        #     signed_psbt = self.finalize_psbt(signed_psbt)
        # return signed_psbt

    def combine_and_finalize_psbt(
        self,
        *,
        initial_psbt: PSBT,
        signed_psbts: list[PSBT],
    ):
        psbt = initial_psbt.clone()
        for signed_psbt in signed_psbts:
            psbt = psbt.combine(signed_psbt)
        return self.finalize_psbt(psbt)

    def finalize_psbt(self, psbt: PSBT):
        psbt = psbt.clone()
        sign_result = psbt.sign(KeyStore(), finalize=True)
        if not sign_result.is_final:
            raise ValueError("Failed to finalize PSBT")
        return psbt

    def broadcast_psbt(self, psbt: PSBT):
        tx = psbt.extract_transaction()
        tx_hex = tx.serialize().hex()
        accept_result = self._bitcoin_rpc.call("testmempoolaccept", [tx_hex])
        if not accept_result[0]["allowed"]:
            reason = accept_result[0].get("reject-reason")
            raise ValueError(f"Transaction rejected by mempool: {reason}")
        txid = self._bitcoin_rpc.call("sendrawtransaction", tx_hex)
        return txid

    def derive_address(self, index) -> str:
        redeem_script = self._derive_redeem_script(index)
        p2wsh = P2WSHBitcoinAddress.from_redeemScript(redeem_script)
        return encode_segwit_address(p2wsh)

    # Helpers for PSBT serialization
    def serialize_psbt(self, psbt: PSBT) -> str:
        return psbt.to_base64()

    def deserialize_psbt(self, raw: str) -> PSBT:
        return PSBT.from_base64(raw)

    def _derive_redeem_script(self, index: int) -> CScript:
        sorted_child_pubkeys = [
            xpub.derive_path(self._base_derivation_path).derive(index).pub
            for xpub in self._master_xpubs
        ]
        sorted_child_pubkeys.sort()

        return standard_multisig_redeem_script(
            total=len(self._master_xpubs),
            required=self._num_required_signers,
            pubkeys=sorted_child_pubkeys,
        )

    def _list_utxos(self) -> list[UTXO]:
        # Don't filter by address here as we want all UTXOs
        raw_utxos = self._bitcoin_rpc.listunspent(1, 9999999, [], False)
        utxos = [UTXO.from_rpc_response(utxo) for utxo in raw_utxos]
        utxos.sort(key=lambda utxo: utxo.confirmations, reverse=True)
        return utxos
