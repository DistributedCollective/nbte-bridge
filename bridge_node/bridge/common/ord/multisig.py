import logging

from bitcointx.core.script import standard_multisig_redeem_script
from bitcointx.wallet import CCoinExtKey, CCoinExtPubKey, P2WSHBitcoinAddress

from .client import OrdApiClient
from ..btc.rpc import BitcoinRPC
from ..btc.types import UTXO
from ..btc.utils import encode_segwit_address
from ..btc import descriptors
from .utxos import OrdOutputCache

logger = logging.getLogger(__name__)


class OrdMultisig:
    def __init__(
        self,
        *,
        master_xpriv: str,
        master_xpubs: list[str],
        num_required_signers: int,
        key_derivation_path: str,
        bitcoin_rpc: BitcoinRPC,
        ord_client: OrdApiClient,
    ):
        _xprv = CCoinExtKey(master_xpriv)
        self._get_master_xpriv = lambda: _xprv
        self._master_xpubs = [CCoinExtPubKey(xpub) for xpub in master_xpubs]
        self._num_required_signers = num_required_signers
        if not key_derivation_path.startswith("m"):
            raise ValueError("key_derivation_path must start with 'm'")
        self._key_derivation_path = key_derivation_path
        self._bitcoin_rpc = bitcoin_rpc

        sorted_child_pubkeys = [
            xpub.derive_path(self._key_derivation_path).pub for xpub in self._master_xpubs
        ]
        sorted_child_pubkeys.sort()

        # This implementation only cares about a single address for nw
        self._multisig_redeem_script = standard_multisig_redeem_script(
            total=len(self._master_xpubs),
            required=num_required_signers,
            pubkeys=sorted_child_pubkeys,
        )
        self._multisig_script = P2WSHBitcoinAddress.from_redeemScript(self._multisig_redeem_script)
        self._multisig_address = encode_segwit_address(self._multisig_script)

        # Ord stuff
        self._ord_client = ord_client
        self._ord_output_cache = OrdOutputCache(
            ord_client=ord_client,
        )

    @property
    def change_address(self):
        return self._multisig_address

    def get_descriptor(self):
        required = self._num_required_signers
        xpubs_str = ",".join(
            self._key_derivation_path.replace("m", str(xpub)) for xpub in self._master_xpubs
        )
        descriptor = f"wsh(sortedmulti({required},{xpubs_str}))"
        return descriptors.descsum_create(descriptor)

    def get_rune_balance(self, rune_name: str) -> int:
        utxos = self._list_utxos()
        return sum(
            self._ord_output_cache.get_ord_output(
                txid=utxo.txid,
                vout=utxo.vout,
            ).get_rune_balance(rune_name)
            for utxo in utxos
        )

    def _list_utxos(self):
        raw_utxos = self._bitcoin_rpc.listunspent(1, 9999999, [self._multisig_address], False)
        utxos = [UTXO.from_rpc_response(utxo) for utxo in raw_utxos]
        utxos.sort(key=lambda utxo: utxo.confirmations, reverse=True)
        return utxos
