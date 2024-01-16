import binascii
from io import BytesIO

from anemic.ioc import service, Container

from bitcointx.core import CTransaction, CTxIn, CTxOut
from bitcointx.wallet import CCoinExtPubKey, CCoinExtKey, P2WSHBitcoinAddress
from bitcointx.core.script import standard_multisig_redeem_script

from .rpc import BitcoinRPC
from .utils import encode_segwit_address
from .types import Transfer, PSBT, UTXO


class BitcoinMultisig:
    def __init__(
        self,
        *,
        master_xpriv: str,
        master_xpubs: list[str],
        num_required_signers: int,
        key_derivation_path: str,
        bitcoin_rpc: BitcoinRPC,
    ):
        _xprv = CCoinExtKey(master_xpriv)
        self._get_master_xpriv = lambda: _xprv
        self._master_xpubs = [CCoinExtPubKey(xpub) for xpub in master_xpubs]
        self._num_required_signers = num_required_signers
        self._key_derivation_path = key_derivation_path
        self._bitcoin_rpc = bitcoin_rpc

        sorted_child_pubkeys = [
            xpub.derive_path(self._key_derivation_path).pub for xpub in self._master_xpubs
        ]
        sorted_child_pubkeys.sort()

        self._multisig_redeem_script = standard_multisig_redeem_script(
            total=len(self._master_xpubs),
            required=num_required_signers,
            pubkeys=sorted_child_pubkeys,
        )
        self._multisig_script = P2WSHBitcoinAddress.from_redeemScript(self._multisig_redeem_script)
        self._multisig_address = encode_segwit_address(self._multisig_script)

    def construct_psbt(self, transfers: list[Transfer]):
        """
        Construct a Partially Signed Bitcoin Transaction (PSBT) for the given transfers.
        """
        # Validation
        for transfer in transfers:
            transfer.assert_valid()

        # Output calculation (disregarding change output)
        vout: list[CTxOut] = [
            CTxOut(
                nValue=transfer.amount_satoshi,
                scriptPubKey=transfer.recipient_script_pubkey,
            )
            for transfer in transfers
        ]
        total_transfer_amount_satoshi = sum(transfer.amount_satoshi for transfer in transfers)

        # Coin selection/input calculation
        utxos = self._list_utxos()
        input_amount_satoshi = 0
        input_txs = []
        vin: list[CTxIn] = []
        for utxo in utxos:
            input_tx_raw = self._bitcoin_rpc.gettransaction(utxo.txid, True)
            input_tx = CTransaction.stream_deserialize(
                BytesIO(binascii.unhexlify(input_tx_raw["hex"])),
            )
            input_txs.append(input_tx)

            input_amount_satoshi += utxo.amount_satoshi
            vin.append(
                CTxIn(
                    prevout=utxo.outpoint,
                )
            )
            fee_satoshi = self._calculate_fee(
                vin=vin,
                vout=vout,
                add_change_out=True,
                fee_rate_sats_per_vbyte=50,  # TODO: proper fee rate estimation!
            )
            if input_amount_satoshi >= total_transfer_amount_satoshi + fee_satoshi:
                break
        else:
            raise Exception("Not enough funds to cover transfer + fee")

        change_amount_satoshi = input_amount_satoshi - total_transfer_amount_satoshi - fee_satoshi
        assert change_amount_satoshi >= 0
        if change_amount_satoshi > 0:
            vout.append(
                CTxOut(
                    nValue=change_amount_satoshi,
                    scriptPubKey=self._multisig_script.to_scriptPubKey(),
                )
            )

        unsigned_tx = CTransaction(
            vin=vin,
            vout=vout,
        )
        psbt = PSBT(
            unsigned_tx=unsigned_tx,
        )
        for i, psbt_input in enumerate(psbt.inputs):
            psbt_input.witness_script = self._multisig_redeem_script
            psbt.set_utxo(
                index=i,
                utxo=input_txs[i],
                force_witness_utxo=True,
            )
        return psbt

    def _list_utxos(self) -> list[UTXO]:
        raw_utxos = self._bitcoin_rpc.listunspent(0, 9999999, [self._multisig_address], False)
        utxos = [UTXO.from_rpc_response(utxo) for utxo in raw_utxos]
        utxos.sort(key=lambda utxo: utxo.confirmations, reverse=True)
        return utxos

    def _calculate_fee(
        self,
        *,
        vin: list[CTxIn],
        vout: list[CTxOut],
        add_change_out: bool,
        fee_rate_sats_per_vbyte: int,
    ) -> int:
        """
        Calculate the fee for a transaction with the given inputs and outputs.

        We just create a temporary CTransaction here to utilize bitcointx's virtual size calculation.
        """
        # TODO: this does not handle witness or scriptSigs correctly
        vout = vout[:]
        vin = vin[:]
        if add_change_out:
            vout.append(
                CTxOut(nValue=1, scriptPubKey=self._multisig_script.to_scriptPubKey()),
            )
        tx = CTransaction(
            vin=vin,
            vout=vout,
        )
        return tx.get_virtual_size() * fee_rate_sats_per_vbyte


@service(scope="global", interface_override=BitcoinMultisig)
def bitcoin_multisig_factory(container: Container):
    from bridge.config import Config

    config = container.get(interface=Config)
    return BitcoinMultisig(
        master_xpriv=config.btc_master_private_key,
        master_xpubs=config.btc_master_public_keys,
        num_required_signers=config.btc_num_required_signers,
        key_derivation_path=config.btc_key_derivation_path,
        bitcoin_rpc=container.get(interface=BitcoinRPC),
    )
