# Implement everything rune bridge related here until we have a proper implementation
# TODO: obviously get rid of this module
from web3 import Web3
import logging
from dataclasses import dataclass
from decimal import Decimal

import requests
from eth_utils import to_checksum_address, add_0x_prefix
from anemic.ioc import Container, auto, autowired, service
from bridge.common.btc.rpc import BitcoinRPC
from .evm import load_rune_bridge_abi


logger = logging.getLogger(__name__)


@dataclass
class RuneToEvmTransfer:
    evm_address: str
    amount_raw: int
    amount_decimal: Decimal
    txid: str
    vout: int
    rune_name: str


@service(scope="global")
class FauxRuneService:
    web3: Web3 = autowired(auto)

    bitcoin_rpc_root: BitcoinRPC
    bitcoin_rpc: BitcoinRPC
    ord_api_url = "http://alice-ord"

    last_bitcoin_block: str | None = None
    # _evm_addresses_by_deposit_address: dict[str, str]

    def __init__(self, container: Container):
        self.container = container
        self.bitcoin_rpc_root = BitcoinRPC(url="http://polaruser:polarpass@bitcoind:18443")
        self.bitcoin_rpc = BitcoinRPC(
            url="http://polaruser:polarpass@bitcoind:18443/wallet/alice-ord"
        )
        self.rune_bridge_contract = self.web3.eth.contract(
            address=to_checksum_address("0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9"),
            abi=load_rune_bridge_abi("RuneBridge"),
        )
        # self._evm_addresses_by_deposit_address = {}

    def _ensure_bitcoin_wallet(self):
        wallets = self.bitcoin_rpc_root.call("listwallets")
        if "alice-ord" not in wallets:
            self.bitcoin_rpc_root.call("createwallet", "alice-ord")

    def generate_deposit_address(self, evm_address: str) -> str:
        self._ensure_bitcoin_wallet()

        evm_address = to_checksum_address(evm_address)
        label = f"runes:deposit:{evm_address}"

        # could check existing address here but no need to
        # self.bitcoin_rpc.call("getaddressesbylabel", label)

        return self.bitcoin_rpc.call("getnewaddress", label)

    def scan_rune_deposits(self) -> list[RuneToEvmTransfer]:
        if not self.last_bitcoin_block:
            resp = self.bitcoin_rpc.call("listsinceblock")
        else:
            resp = self.bitcoin_rpc.call("listsinceblock", self.last_bitcoin_block)

        transfers = []
        for tx in resp["transactions"]:
            if tx["category"] != "receive":
                continue
            if "label" not in tx:
                continue
            if not tx["label"].startswith("runes:deposit:"):
                continue
            evm_address = tx["label"][len("runes:deposit:") :]
            txid = tx["txid"]
            vout = tx["vout"]
            outpoint = f"{txid}:{vout}"

            utxos_by_rune = self.ord_api_call("/runes/balances")
            for rune_name, utxos in utxos_by_rune.items():
                if outpoint in utxos:
                    amount_raw = utxos[outpoint]
                    amount_decimal = Decimal(amount_raw) / 10**18
                    break
            else:
                raise ValueError(f"Could not find {outpoint} in {utxos_by_rune}")

            logger.info(
                "Received %s %s for %s at %s:%s", amount_decimal, rune_name, evm_address, txid, vout
            )

            transfer = RuneToEvmTransfer(
                evm_address=evm_address,
                amount_raw=amount_raw,
                amount_decimal=amount_decimal,
                txid=txid,
                vout=vout,
                rune_name=rune_name,
            )
            logger.info("Transfer: %s", transfer)
            transfers.append(transfer)

        self.last_bitcoin_block = resp["lastblock"]
        return transfers

    def send_rune_to_evm(self, transfer: RuneToEvmTransfer):
        logger.info("Executing Rune-to-EVM transfer %s", transfer)
        tx_hash = self.rune_bridge_contract.functions.acceptTransferFromBtc(
            transfer.evm_address,
            transfer.rune_name,
            transfer.amount_raw,
            add_0x_prefix(transfer.txid),
            transfer.vout,
            [],
        ).transact(
            {
                "gas": 10_000_000,
            }
        )
        logger.info("Sent Rune-to-EVM transfer %s, waiting...", tx_hash.hex())
        receipt = self.web3.eth.wait_for_transaction_receipt(
            tx_hash,
            timeout=120,
            poll_latency=2.0,
        )
        assert receipt["status"]
        logger.info("Rune-to-EVM transfer %s confirmed", tx_hash.hex())

    def ord_api_call(self, path):
        return requests.get(
            f"{self.ord_api_url}{path}",
            headers={
                "Accept": "application/json",
            },
        ).json()
