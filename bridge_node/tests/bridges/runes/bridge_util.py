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
from ...services import (
    BitcoindService,
    HardhatService,
    OrdService,
    OrdWallet,
)
from ...services.hardhat import EVMWallet
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
        mine: bool = True,
        verify: bool = None,
    ) -> HexBytes:
        if verify is None:
            verify = mine
        if verify and not mine:
            raise ValueError("mine must be true if verify is true")

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
        if mine:
            self._hardhat.mine()
        if verify:
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

    # ASSERTION HELPERS

    def assert_balances(
        self,
        *,
        rune: str,
        user_ord_wallet: OrdWallet = None,
        user_evm_wallet: EVMWallet = None,
        expected_user_token_balance_decimal: Decimalish = None,
        expected_user_rune_balance_decimal: Decimalish = None,
        expected_token_total_supply_decimal: Decimalish = None,
        expected_bridge_token_balance_decimal: Decimalish = None,
        expected_bridge_rune_balance_decimal: Decimalish = None,
    ):
        rune_token = self.get_rune_token(rune)

        if expected_user_token_balance_decimal is not None:
            if user_evm_wallet is None:
                raise ValueError(
                    "user_evm_wallet must be provided to if expected_user_token_balance_decimal is provided"
                )
            user_token_balance = from_wei(
                rune_token.functions.balanceOf(user_evm_wallet.address).call()
            )
            self._assert_decimals_equal(
                user_token_balance,
                expected_user_token_balance_decimal,
                "user_token_balance",
            )

        if expected_user_rune_balance_decimal is not None:
            if user_ord_wallet is None:
                raise ValueError(
                    "user_ord_wallet must be provided to if expected_user_rune_balance_decimal is provided"
                )
            user_rune_balance = user_ord_wallet.get_rune_balance_decimal(rune)
            self._assert_decimals_equal(
                user_rune_balance,
                expected_user_rune_balance_decimal,
                "user_rune_balance",
            )

        if expected_token_total_supply_decimal is not None:
            token_total_supply = from_wei(rune_token.functions.totalSupply().call())
            self._assert_decimals_equal(
                token_total_supply,
                expected_token_total_supply_decimal,
                "token_total_supply",
            )

        if expected_bridge_token_balance_decimal is not None:
            bridge_token_balance = from_wei(
                rune_token.functions.balanceOf(self._rune_bridge_contract.address).call()
            )
            self._assert_decimals_equal(
                bridge_token_balance,
                expected_bridge_token_balance_decimal,
                "bridge_token_balance",
            )

        if expected_bridge_rune_balance_decimal is not None:
            rune_response = self._ord.api_client.get_rune(rune)
            if not rune_response:
                raise ValueError(f"rune {rune} not found")
            bridge_rune_balance = self._bridge_ord_multisig.get_rune_balance(rune)
            bridge_rune_balance = Decimal(bridge_rune_balance) / (
                10 ** rune_response["entry"]["divisibility"]
            )
            self._assert_decimals_equal(
                bridge_rune_balance,
                expected_bridge_rune_balance_decimal,
                "bridge_rune_balance",
            )

    def _assert_equal(self, a, b, context: str = ""):
        assert a == b, f"{context}: {a} != {b}"

    def _assert_decimals_equal(self, a: Decimalish, b: Decimalish, context: str = ""):
        self._assert_equal(Decimal(a), Decimal(b), context=context)
