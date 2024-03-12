from decimal import Decimal
from dataclasses import dataclass
import logging
import time
from bitcointx.core import CTransaction, CTxIn, CTxOut, COutPoint
import bitcointx
from bitcointx.wallet import CCoinAddress
from bitcointx.core.script import CScript
from pyord import RuneId, Runestone, Edict
from .client import OrdApiClient
from bridge.common.btc.rpc import BitcoinRPC


TARGET_POSTAGE = 10_000  # sat locked in rune outputs
logger = logging.getLogger(__name__)

bitcointx.select_chain_params("bitcoin/regtest")


@dataclass
class RunicUTXO:
    rune_name: str
    amount_decimal: Decimal
    amount_raw: int


@dataclass
class InscriptionUTXO:
    inscription_id: str


class LazyOrdUTXO:
    def __init__(
        self,
        *,
        txid: str,
        vout: int,
        amount_decimal: Decimal,
        confirmations: int,
        ord_client: OrdApiClient,
    ):
        self.txid = txid
        self.vout = vout
        self.amount_sat = int(amount_decimal * 10**8)
        self.confirmations = confirmations
        self._ord_client = ord_client
        self._ord_response = None

    @property
    def runic_utxos(self) -> list[RunicUTXO]:
        self._ensure_ord_response()
        return [
            RunicUTXO(
                rune_name=rune_name,
                amount_decimal=Decimal(entry["amount"]) / (Decimal(10) ** entry["divisibility"]),
                amount_raw=entry["amount"],
            )
            for (rune_name, entry) in self._ord_response["runes"]
        ]

    @property
    def inscription_utxos(self) -> list[InscriptionUTXO]:
        self._ensure_ord_response()
        return [
            InscriptionUTXO(inscription_id=inscription_id)
            for inscription_id in self._ord_response["inscriptions"]
        ]

    @property
    def has_ord_balances(self):
        self._ensure_ord_response()
        return bool(self.runic_utxos or self.inscription_utxos)

    def get_rune_balance(self, rune_name: str) -> int:
        self._ensure_ord_response()
        return sum(
            (u.amount_raw for u in self.runic_utxos if u.rune_name == rune_name),
            start=0,
        )

    def __repr__(self):
        return f"UTXO(txid={self.txid}, vout={self.vout}, amount={self.amount_sat}, confirmations={self.confirmations})"

    def _ensure_ord_response(self):
        if self._ord_response is None:
            self._ord_response = self._ord_client.get(f"/output/{self.txid}:{self.vout}")


class SimpleOrdWallet:
    """
    Simple Ord wallet, no multisig goodiness
    """

    def __init__(
        self,
        *,
        ord_client: OrdApiClient,
        bitcoin_rpc: BitcoinRPC,
    ):
        self._ord_client = ord_client
        self._bitcoin_rpc = bitcoin_rpc

    def list_utxos(self) -> list[LazyOrdUTXO]:
        block_count = self._get_btc_block_count()
        utxos = self._bitcoin_rpc.call("listunspent", 1, 9999999, [], False)
        self._wait_for_ord_sync(block_count)
        utxos = [
            LazyOrdUTXO(
                txid=utxo["txid"],
                vout=utxo["vout"],
                amount_decimal=Decimal(utxo["amount"]),
                confirmations=utxo["confirmations"],
                ord_client=self._ord_client,
            )
            for utxo in utxos
        ]
        utxos.sort(key=lambda utxo: utxo.confirmations, reverse=True)
        return utxos

    def generate_address(self) -> str:
        return self._bitcoin_rpc.call("getnewaddress")

    def get_btc_balance(self) -> Decimal:
        utxos = self.list_utxos()
        return sum(
            (utxo.amount for utxo in utxos if not utxo.has_ord_balances),
            start=Decimal(0),
        )

    def get_rune_balance(self, rune_name: str) -> Decimal:
        utxos = self.list_utxos()
        return sum(
            (utxo.get_rune_balance(rune_name) for utxo in utxos),
            start=Decimal(0),
        )

    def send_runes(self, *, rune_name: str, amount: Decimal, receiver_address: str) -> Decimal:
        rune = self._ord_client.get_rune(rune_name)
        if not rune:
            raise ValueError(f"Rune {rune_name} not found")
        if amount < 0:
            raise ValueError("Amount must be non-negative")

        receiver = CCoinAddress(receiver_address)
        amount_raw = int(amount * (10 ** rune["entry"]["divisibility"]))
        block_height, tx_index = map(int, rune["id"].split(":"))
        rune_id = RuneId(
            height=block_height,
            index=tx_index,
        )

        utxos = self.list_utxos()
        inputs = []
        total_runes_in = 0
        total_sat_in = 0
        for utxo in utxos:
            rune_balance_at_utxo = utxo.get_rune_balance(rune_name)
            if rune_balance_at_utxo > 0:
                inputs.append(
                    CTxIn(
                        prevout=COutPoint(
                            hash=bytes.fromhex(utxo.txid)[::-1],
                            n=utxo.vout,
                        ),
                    )
                )
                total_runes_in += rune_balance_at_utxo
                total_sat_in += utxo.amount_sat
                if total_runes_in >= amount_raw:
                    break
        else:
            raise ValueError(
                f"Insufficient rune balance for {amount_raw} {rune_name} (can only send {total_runes_in})"
            )

        fee = TARGET_POSTAGE  # TODO: real fee
        target_sats_out = TARGET_POSTAGE + fee
        if total_sat_in < target_sats_out:
            for utxo in utxos:
                if utxo.has_ord_balances:
                    continue
                inputs.append(
                    CTxIn(
                        prevout=COutPoint(
                            hash=bytes.fromhex(utxo.txid)[::-1],
                            n=utxo.vout,
                        ),
                    )
                )
                total_sat_in += utxo.amount_sat
                if total_sat_in >= target_sats_out:
                    break
            else:
                raise ValueError(
                    f"Insufficient BTC balance. Can only send {total_sat_in} sat (need {target_sats_out})"
                )

        runestone = Runestone(
            edicts=[
                Edict(
                    id=rune_id.num,
                    amount=amount_raw,
                    output=1,  # receiver is first output
                )
            ],
            # change is second output. runes left over from edicts are automatically sent to change address
            default_output=2,
        )
        change_address = CCoinAddress(self.generate_address())
        outputs = [
            CTxOut(
                nValue=0,
                scriptPubKey=CScript(runestone.script_pubkey()),
            ),
            CTxOut(nValue=TARGET_POSTAGE, scriptPubKey=receiver.to_scriptPubKey()),
            CTxOut(
                nValue=total_sat_in - TARGET_POSTAGE - fee,
                scriptPubKey=change_address.to_scriptPubKey(),
            ),
        ]
        tx = CTransaction(
            vin=inputs,
            vout=outputs,
        )
        signed_tx = self._bitcoin_rpc.call("signrawtransactionwithwallet", tx.serialize().hex())
        return self._bitcoin_rpc.call("sendrawtransaction", signed_tx["hex"])

    def _get_btc_block_count(self) -> int:
        return self._bitcoin_rpc.call("getblockcount")

    def _wait_for_ord_sync(self, block_count: int, *, poll_interval=1.0, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            ord_block_count = self._ord_client.get("/blockcount")
            if ord_block_count >= block_count:
                break
            logger.info(
                "Waiting for ord to sync to block %d (current: %d)", block_count, ord_block_count
            )
            time.sleep(poll_interval)
        else:
            raise TimeoutError("ORD did not sync in time")
