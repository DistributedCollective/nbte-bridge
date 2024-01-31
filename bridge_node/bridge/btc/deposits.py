import dataclasses
import logging

from anemic.ioc import Container, service, autowired, auto

from sqlalchemy.orm.session import Session

from .multisig import BitcoinMultisig
from .derivation import DepositAddressInfo
from .rpc import BitcoinRPC
from .utils import to_satoshi

from ..common.key_value_store import KeyValueStore

logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class BitcoinDeposit:
    amount_satoshi: int
    txid: str
    vout: int
    address_info: DepositAddressInfo


@service(scope="transaction")
class BitcoinDepositService:
    btc_multisig: BitcoinMultisig = autowired(auto)
    bitcoin_rpc: BitcoinRPC = autowired(auto)
    key_value_store: KeyValueStore = autowired(auto)
    dbsession: Session = autowired(auto)

    def __init__(self, container: Container):
        self.container = container

    def generate_deposit_address(
        self,
        evm_address: str,
        index: int,
    ) -> DepositAddressInfo:
        # TODO: database, validation, etc
        info = self.btc_multisig.derive_deposit_address_info(
            evm_address=evm_address,
            index=index,
        )
        logger.info(
            "Importing deposit address %s (%s:%d)",
            info.btc_deposit_address,
            info.evm_address,
            info.index,
        )
        label = f"deposit:{evm_address}:{index}"
        result = self.bitcoin_rpc.importaddress(info.btc_deposit_address, label, False)
        logger.info("Imported, result: %s", result)
        return info

    def scan_new_deposits(self):
        # TODO: database, etc
        # listsinceblock output looks like this:
        # {
        #     "transactions": [
        #         {
        #             "involvesWatchonly": true,
        #             "address": "bcrt1qf99f7nmqzxulvn92lvk0rlvkur0f3fsldg8hd4w8z0ztwddpyx6sdge5ln",
        #             "category": "receive",
        #             "amount": 0.01000000,
        #             "label": "0x64941c4349b58617763246311DCa009a8dbD9059:0",
        #             "vout": 0,
        #             "confirmations": 6,
        #             "blockhash": "5787833ac84a02703947a9f2644e2104accc796eabfc37e50a491f74af7ccf2c",
        #             "blockheight": 1835,
        #             "blockindex": 1,
        #             "blocktime": 1706012840,
        #             "txid": "831bf838b8c022af9f3646c6fe6a3643b67f37f156f7760ffbc388f976bcf793",
        #             "walletconflicts": [
        #             ],
        #             "time": 1706012830,
        #             "timereceived": 1706012830,
        #             "bip125-replaceable": "no"
        #         },
        #     ],
        #     "removed": [
        #     ],
        #     "lastblock": "648479dacee23b12962046323ebe2d67236c4fcace22df959650e3197734635b"
        # }
        last_block_key = "btc:deposits:last-scanned-block"
        last_block = self.key_value_store.get_value(last_block_key, None)
        deposits = []
        if last_block is None:
            result = self.bitcoin_rpc.listsinceblock()
        else:
            result = self.bitcoin_rpc.listsinceblock(last_block)
        for tx in result["transactions"]:
            label = tx.get("label", "")
            if not label.startswith("deposit:"):
                continue
            amount_btc = tx["amount"]
            if amount_btc <= 0:
                logger.warning("Ignoring deposit with amount <= 0: %s", tx)
                continue

            _, evm_address, index = label.split(":")
            index = int(index)
            info = self.btc_multisig.derive_deposit_address_info(
                evm_address=evm_address,
                index=index,
            )
            # this address is not the receiving address, but the user's address
            # assert info.btc_deposit_address == tx["address"]
            amount_satoshi = to_satoshi(amount_btc)
            deposits.append(
                BitcoinDeposit(
                    amount_satoshi=amount_satoshi,
                    txid=tx["txid"],
                    vout=tx["vout"],
                    address_info=info,
                )
            )
        self.key_value_store.set_value(last_block_key, result["lastblock"])
        return deposits
