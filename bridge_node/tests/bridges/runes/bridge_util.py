from decimal import Decimal

from hexbytes import HexBytes
from sqlalchemy.orm import (
    Session,
)
from web3.contract import Contract

from bridge.bridges.runes.bridge import RuneBridge
from bridge.bridges.runes.evm import load_rune_bridge_abi
from bridge.bridges.runes.service import RuneBridgeService
from bridge.common.evm.utils import (
    from_wei,
    to_wei,
)
from bridge.common.ord.multisig import OrdMultisig
from .balances import BalanceSnapshot
from ...services import (
    BitcoindService,
    HardhatService,
    OrdService,
    OrdWallet,
)
from ...services.hardhat import EVMWallet
from ...services.ord import EtchingInfo
from ...utils.types import Decimalish


class RuneBridgeUtil:
    """
    This class encompasses Rune Bridge use cases and provides a simplified interface for testing.
    """

    def __init__(
        self,
        *,
        ord: OrdService,
        hardhat: HardhatService,
        bitcoind: BitcoindService,
        rune_bridge: RuneBridge,
        rune_bridge_service: RuneBridgeService,
        rune_bridge_contract: Contract,
        root_ord_wallet: OrdWallet,
        bridge_ord_multisig: OrdMultisig,
        dbsession: Session,
    ):
        self._ord = ord
        self._hardhat = hardhat
        self._bitcoind = bitcoind
        self._rune_bridge = rune_bridge
        self._rune_bridge_service = rune_bridge_service
        self._rune_bridge_contract = rune_bridge_contract
        self._root_ord_wallet = root_ord_wallet
        self._bridge_ord_multisig = bridge_ord_multisig
        self._dbsession = dbsession

    # USE CASES

    def run_bridge_iteration(self, *, mine: bool = True):
        self._rune_bridge.run_iteration()
        if mine:
            self.mine()

    def get_deposit_address(self, evm_address: str):
        with self._dbsession.begin():
            return self._rune_bridge_service.generate_deposit_address(
                evm_address=evm_address,
                dbsession=self._dbsession,
            )

    def get_rune_token(self, rune: str) -> Contract:
        address = self._rune_bridge_contract.functions.getTokenByRune(rune).call()
        return self._hardhat.web3.eth.contract(
            address=address,
            abi=load_rune_bridge_abi("RuneSideToken"),
        )

    def register_rune(
        self,
        *,
        rune: str,
        symbol: str = None,
    ) -> Contract:
        if not symbol:
            symbol = rune[0]
        # TODO: use the smart contract directly
        self._hardhat.run_json_command(
            "runes-register-rune",
            "--bridge-address",
            self._rune_bridge_contract.address,
            "--rune-name",
            rune,
            "--rune-symbol",
            symbol,
        )
        return self.get_rune_token(rune)

    def transfer_runes_to_evm(
        self,
        *,
        wallet: OrdWallet,
        amount_decimal: int,
        deposit_address: str,
        rune: str,
        mine: bool = True,
    ):
        wallet.send_runes(
            rune=rune,
            amount_decimal=amount_decimal,
            receiver=deposit_address,
        )
        if mine:
            self._ord.mine_and_sync()

    def transfer_rune_tokens_to_bitcoin(
        self,
        *,
        sender: str | EVMWallet,
        amount_decimal: Decimalish,
        receiver_address: str,
        rune_token_address: str = None,
        rune: str = None,
        verify: bool = True,
    ) -> HexBytes:
        if not rune and not rune_token_address:
            raise ValueError("either rune or rune_token_address must be provided")
        if rune and rune_token_address:
            raise ValueError("only one of rune or rune_token_address must be provided")
        if rune:
            rune_token_address = self.get_rune_token(rune).address

        if isinstance(sender, EVMWallet):
            sender = sender.address

        amount_decimal = Decimal(amount_decimal)

        tx_hash = self._rune_bridge_contract.functions.transferToBtc(
            rune_token_address,
            to_wei(amount_decimal),
            receiver_address,
        ).transact(
            {
                "gas": 1_000_000,
                "from": sender,
            }
        )
        if verify:
            # Automining is on, no need to mine
            receipt = self._hardhat.web3.eth.get_transaction_receipt(tx_hash)
            assert receipt.status
        return HexBytes(tx_hash)

    # GENERIC HELPERS

    def mine(self, *, bitcoin_blocks: int = 1, evm_blocks: int = 1):
        if bitcoin_blocks:
            self._bitcoind.mine(bitcoin_blocks)
            self._ord.sync_with_bitcoind()
        if evm_blocks:
            self._hardhat.mine(evm_blocks)

    def fund_wallet_with_runes(self, *, wallet: OrdWallet, amount_decimal: Decimalish, rune: str):
        self._root_ord_wallet.send_runes(
            rune=rune,
            amount_decimal=amount_decimal,
            receiver=wallet.get_receiving_address(),
        )
        self._ord.mine_and_sync()

    def etch_test_rune(
        self,
        prefix: str,
        **kwargs,
    ) -> EtchingInfo:
        return self._root_ord_wallet.etch_test_rune(prefix, **kwargs)

    def etch_and_register_test_rune(
        self,
        prefix: str,
        fund: tuple[OrdWallet, Decimalish] = None,
        **kwargs,
    ) -> str:
        etching = self.etch_test_rune(prefix, **kwargs)
        if fund:
            wallet, amount_decimal = fund
            self.fund_wallet_with_runes(
                wallet=wallet, amount_decimal=amount_decimal, rune=etching.rune
            )
        self.register_rune(rune=etching.rune, symbol=etching.rune_symbol)
        return etching.rune

    # BALANCE HELPERS

    def snapshot_balances(
        self,
        *,
        rune: str,
        user_ord_wallet: OrdWallet,
        user_evm_wallet: EVMWallet,
    ):
        rune_response = self._ord.api_client.get_rune(rune)
        if not rune_response:
            raise ValueError(f"rune {rune} not found")
        rune_divisor = 10 ** rune_response["entry"]["divisibility"]
        rune_token = self.get_rune_token(rune)

        return BalanceSnapshot(
            rune=rune,
            rune_entry=rune_response["entry"],
            rune_token=rune_token,
            user_ord_wallet=user_ord_wallet,
            user_evm_wallet=user_evm_wallet,
            user_token_balance_decimal=from_wei(
                rune_token.functions.balanceOf(user_evm_wallet.address).call()
            ),
            user_rune_balance_decimal=user_ord_wallet.get_rune_balance_decimal(rune),
            token_total_supply_decimal=from_wei(rune_token.functions.totalSupply().call()),
            bridge_token_balance_decimal=from_wei(
                rune_token.functions.balanceOf(self._rune_bridge_contract.address).call()
            ),
            bridge_rune_balance_decimal=self._bridge_ord_multisig.get_rune_balance(rune)
            / rune_divisor,
        )

    def snapshot_balances_again(self, snapshot: BalanceSnapshot) -> BalanceSnapshot:
        return self.snapshot_balances(
            rune=snapshot.rune,
            user_ord_wallet=snapshot.user_ord_wallet,
            user_evm_wallet=snapshot.user_evm_wallet,
        )

    def snapshot_balance_changes(
        self, snapshot: BalanceSnapshot
    ) -> tuple[BalanceSnapshot, BalanceSnapshot]:
        """
        Get a tuple of (current_snapshot, changes)
        """
        new_snapshot = self.snapshot_balances_again(snapshot)
        return new_snapshot - snapshot, new_snapshot

    # ASSERTION HELPERS

    def assert_runes_to_evm_transfer_happened(
        self,
        *,
        amount_decimal: str,
        rune: str,
    ):
        pass
