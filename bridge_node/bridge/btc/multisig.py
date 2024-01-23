import binascii
from io import BytesIO
import logging
from types import SimpleNamespace

from anemic.ioc import service, Container

from bitcointx.core import (
    CTransaction,
    CTxIn,
    CTxInWitness,
    CTxOut,
    CTxWitness,
    calculate_transaction_virtual_size,
)
from bitcointx.wallet import CCoinExtPubKey, CCoinExtKey, P2WSHBitcoinAddress
from bitcointx.core.script import CScriptWitness, standard_multisig_redeem_script
from bitcointx.core.key import KeyStore
from bitcointx.core.psbt import PSBT_Input, PSBT_Output

from .rpc import BitcoinRPC
from .utils import encode_segwit_address, from_satoshi
from .types import Transfer, PSBT, UTXO
from .derivation import DepositAddressInfo, derive_deposit_address_info


logger = logging.getLogger(__name__)


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

        # TODO: proper fee rate!
        fee_rate_sats_per_vbyte = 50

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
        psbt = PSBT()
        for txout in vout:
            psbt.add_output(
                txout=txout,
                outp=PSBT_Output(),
            )
        # we don't need to initialize fee_satoshi here -- the for loop is quaranteed to run through at least one
        # iteration or an exception will be raised in the else clause
        for utxo in utxos:
            input_tx_raw = self._bitcoin_rpc.gettransaction(utxo.txid, True)
            input_tx = CTransaction.stream_deserialize(
                BytesIO(binascii.unhexlify(input_tx_raw["hex"])),
            )

            input_amount_satoshi += utxo.amount_satoshi

            psbt.add_input(
                txin=CTxIn(
                    prevout=utxo.outpoint,
                ),
                inp=PSBT_Input(
                    witness_script=self._multisig_redeem_script,
                    utxo=input_tx.vout[utxo.vout],
                    force_witness_utxo=True,
                ),
            )
            fee_satoshi = (
                self._get_virtual_size(
                    psbt=psbt,
                    add_change_out=True,
                )
                * fee_rate_sats_per_vbyte
            )
            if input_amount_satoshi >= total_transfer_amount_satoshi + fee_satoshi:
                break
        else:
            raise Exception("Not enough funds to cover transfer + fee")

        change_amount_satoshi = input_amount_satoshi - total_transfer_amount_satoshi - fee_satoshi
        assert change_amount_satoshi >= 0
        if change_amount_satoshi > 0:
            psbt.add_output(
                txout=CTxOut(
                    nValue=change_amount_satoshi,
                    scriptPubKey=self._multisig_script.to_scriptPubKey(),
                ),
                outp=PSBT_Output(),
            )
        assert psbt.get_fee() == fee_satoshi
        return psbt

    def sign_psbt(self, psbt: PSBT) -> PSBT:
        psbt = psbt.clone()
        keystore = KeyStore.from_iterable(
            [
                self._get_master_xpriv().derive_path(self._key_derivation_path).priv,
            ],
        )
        result = psbt.sign(keystore, finalize=False)
        assert result.num_inputs_signed == len(psbt.inputs)
        return psbt

    def combine_and_finalize_psbt(
        self,
        *,
        initial_psbt: PSBT,
        signed_psbts: list[PSBT],
    ):
        psbt = initial_psbt.clone()
        for signed_psbt in signed_psbts:
            psbt = psbt.combine(signed_psbt)
        sign_result = psbt.sign(KeyStore(), finalize=True)
        if not sign_result.is_final:
            raise Exception("Failed to finalize PSBT")
        return psbt

    def broadcast_psbt(self, psbt: PSBT):
        tx = psbt.extract_transaction()
        tx_hex = tx.serialize().hex()
        accept_result = self._bitcoin_rpc.testmempoolaccept([tx_hex])
        if not accept_result[0]["allowed"]:
            raise ValueError(
                f"Transaction rejected by mempool: {accept_result[0].get('reject-reason')}"
            )
        txid = self._bitcoin_rpc.sendrawtransaction(tx_hex)
        return txid

    def generate_deposit_address(
        self,
        evm_address: str,
        index: int,
    ) -> DepositAddressInfo:
        # TODO: database, validation, etc
        info = derive_deposit_address_info(
            master_xpubs=self._master_xpubs,
            num_required_signers=self._num_required_signers,
            evm_address=evm_address,
            index=index,
            base_derivation_path=self._key_derivation_path,
        )
        logger.info(
            "Importing deposit address %s (%s:%d)",
            info.btc_deposit_address,
            info.evm_address,
            info.index,
        )
        label = f"deposit:{evm_address}:{index}"
        result = self._bitcoin_rpc.importaddress(info.btc_deposit_address, label, False)
        logger.info("Imported, result: %s", result)
        return info

    def scan_new_deposits(self):
        # TODO: this should not be a part of the multisig... propably
        """
        {
            "transactions": [
                {
                    "involvesWatchonly": true,
                    "address": "bcrt1qf99f7nmqzxulvn92lvk0rlvkur0f3fsldg8hd4w8z0ztwddpyx6sdge5ln",
                    "category": "receive",
                    "amount": 0.01000000,
                    "label": "0x64941c4349b58617763246311DCa009a8dbD9059:0",
                    "vout": 0,
                    "confirmations": 6,
                    "blockhash": "5787833ac84a02703947a9f2644e2104accc796eabfc37e50a491f74af7ccf2c",
                    "blockheight": 1835,
                    "blockindex": 1,
                    "blocktime": 1706012840,
                    "txid": "831bf838b8c022af9f3646c6fe6a3643b67f37f156f7760ffbc388f976bcf793",
                    "walletconflicts": [
                    ],
                    "time": 1706012830,
                    "timereceived": 1706012830,
                    "bip125-replaceable": "no"
                },
            ],
            "removed": [
            ],
            "lastblock": "648479dacee23b12962046323ebe2d67236c4fcace22df959650e3197734635b"
        }
        """
        # TODO temporary code, implement the real thing
        lastblock = getattr(self, "_btc_lastblock", None)
        deposits = []
        if lastblock is None:
            result = self._bitcoin_rpc.listsinceblock()
        else:
            result = self._bitcoin_rpc.listsinceblock(lastblock)
        for tx in result["transactions"]:
            if not tx["label"].startswith("deposit:"):
                continue
            _, evm_address, index = tx["label"].split(":")
            index = int(index)
            info = derive_deposit_address_info(
                master_xpubs=self._master_xpubs,
                num_required_signers=self._num_required_signers,
                evm_address=evm_address,
                index=index,
            )
            assert info.btc_deposit_address == tx["address"]
            amount_satoshi = from_satoshi(tx["amount"])
            deposits.append(
                SimpleNamespace(
                    amount_satoshi=amount_satoshi,
                    txid=tx["txid"],
                    vout=tx["vout"],
                    address_info=info,
                )
            )
        setattr(self, "_btc_lastblock", result["lastblock"])
        return deposits

    def _list_utxos(self) -> list[UTXO]:
        raw_utxos = self._bitcoin_rpc.listunspent(0, 9999999, [self._multisig_address], False)
        utxos = [UTXO.from_rpc_response(utxo) for utxo in raw_utxos]
        utxos.sort(key=lambda utxo: utxo.confirmations, reverse=True)
        return utxos

    def _get_virtual_size(
        self,
        *,
        psbt: PSBT,
        add_change_out: bool,
    ) -> int:
        """
        Calculate the (estimated) size in vBytes of a possibly-unsigned PSBT
        """
        # Mostly copied from CTransaction.get_virtual_size, but accounts for witness data and change output
        vin = list(psbt.unsigned_tx.vin)
        vout = list(psbt.unsigned_tx.vout)
        if add_change_out:
            vout.append(CTxOut(nValue=1, scriptPubKey=self._multisig_script.to_scriptPubKey()))

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
        # TODO: we just assume that each input is a P2WSH input (reasonable for this multisig)
        # AND that the signatures are always 71 bytes (might not be 100% accurate but close enough)
        vtxinwit = []
        signature_length_bytes = 71
        for _ in vin:
            vtxinwit.append(
                CTxInWitness(
                    CScriptWitness(
                        stack=[
                            b"",
                            *(
                                b"\x00" * signature_length_bytes
                                for _ in range(self._num_required_signers)
                            ),
                            self._multisig_redeem_script,
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
