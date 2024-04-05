from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from hexbytes import HexBytes
from sqlalchemy.orm import (
    Session,
)
from web3.contract import Contract
from web3.types import EventData

from bridge.bridges.runes.bridge import RuneBridge
from bridge.bridges.runes.evm import load_rune_bridge_abi
from bridge.bridges.runes.models import (
    DepositAddress,
    User,
)
from bridge.bridges.runes.service import RuneBridgeService
from bridge.common.evm.utils import (
    from_wei,
    is_zero_address,
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
from ...utils.timing import measure_time
from ...utils.types import Decimalish

# Use hardhat #0 as default owner, since it's the default deployer
DEFAULT_DEPLOYER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


@dataclass
class RunesToEVMTransfer:
    rune: str
    deposit_address: str
    amount_decimal: Decimal
    txid: str
    evm_block_number: int


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
        bridge_owner_address: str = DEFAULT_DEPLOYER_ADDRESS,
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
        self._bridge_owner_address = bridge_owner_address

        self._web3 = hardhat.web3

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

    def get_rune_token(
        self,
        rune: str,
        *,
        verify_registered: bool = True,
    ) -> Contract:
        address = self._rune_bridge_contract.functions.getTokenByRune(rune).call()
        if verify_registered and is_zero_address(address):
            raise LookupError(f"Rune {rune} not registered on the bridge")
        return self._web3.eth.contract(
            address=address,
            abi=load_rune_bridge_abi("RuneToken"),
        )

    def register_rune(
        self,
        *,
        rune: str,
        symbol: str = None,
    ) -> Contract:
        if not symbol:
            symbol = rune[0]
        with measure_time("register rune"):
            self._rune_bridge_contract.functions.registerRune(rune, symbol).transact(
                {
                    "from": self._bridge_owner_address,
                }
            )
        return self.get_rune_token(rune)

    def transfer_runes_to_evm(
        self,
        *,
        wallet: OrdWallet,
        amount_decimal: Decimalish,
        deposit_address: str,
        rune: str,
        mine: bool = True,
    ) -> RunesToEVMTransfer:
        evm_block_number = self._web3.eth.block_number
        info = wallet.send_runes(
            rune=rune,
            amount_decimal=amount_decimal,
            receiver=deposit_address,
        )
        if mine:
            self._ord.mine_and_sync()
        return RunesToEVMTransfer(
            rune=rune,
            deposit_address=deposit_address,
            amount_decimal=Decimal(amount_decimal),
            txid=info.txid,
            evm_block_number=evm_block_number,
        )

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
            receipt = self._web3.eth.get_transaction_receipt(tx_hash)
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

    def etch_and_register_test_rune(
        self,
        prefix: str,
        fund: tuple[OrdWallet, Decimalish] = None,
        **kwargs,
    ) -> str:
        etching = self._root_ord_wallet.etch_test_rune(prefix, **kwargs)
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

    def assert_runes_transferred_to_evm(self, transfer: RunesToEVMTransfer):
        """
        Assert that the user received the RuneTokens they should based on runes-to-evm transfer
        """
        events = self._get_rune_token_transfer_events(transfer)
        assert len(events) == 1, f"Expected 1 Transfer event, got {len(events)}"
        event = events[-1]
        expected_amount_wei = to_wei(transfer.amount_decimal)
        assert (
            event["args"]["value"] == expected_amount_wei
        ), f"Incorrect amount, got {from_wei(event['args']['value'])}, expected {transfer.amount_decimal}"
        evm_address = self._get_evm_address_from_deposit_address(transfer.deposit_address)
        balance_wei_before = (
            self.get_rune_token(transfer.rune)
            .functions.balanceOf(evm_address)
            .call(
                block_identifier=transfer.evm_block_number,
            )
        )
        balance_wei = self.get_rune_token(transfer.rune).functions.balanceOf(evm_address).call()
        balance_change_wei = balance_wei - balance_wei_before
        assert (
            balance_change_wei == expected_amount_wei
        ), f"Balance change {from_wei(balance_wei)} doesn't match transfer amount {transfer.amount_decimal}"

    def assert_runes_not_transferred_to_evm(self, transfer: RunesToEVMTransfer):
        events = self._get_rune_token_transfer_events(transfer)
        assert len(events) == 0, f"Expected no Transfer events, got {len(events)}"

    def _get_rune_token_transfer_events(self, transfer: RunesToEVMTransfer) -> list[EventData]:
        evm_address = self._get_evm_address_from_deposit_address(transfer.deposit_address)
        assert evm_address, f"Deposit address {transfer.deposit_address} not registered"
        rune_token = self.get_rune_token(transfer.rune, verify_registered=False)
        assert not is_zero_address(
            rune_token.address
        ), f"Rune {transfer.rune} not registered on the bridge"
        # For now, the tokens are minted out of thin air and the "from" address is 0
        # from_address = self._rune_bridge_contract.address
        from_address = "0x0000000000000000000000000000000000000000"
        return rune_token.events.Transfer().get_logs(
            fromBlock=transfer.evm_block_number,
            argument_filters={
                "from": from_address,
                "to": evm_address,
            },
        )

    def _get_evm_address_from_deposit_address(self, deposit_address: str) -> str | None:
        with self._dbsession.begin():
            obj = self._dbsession.scalars(
                sa.select(DepositAddress)
                .join(User)
                .filter(
                    User.bridge_id == self._rune_bridge.bridge_id,
                    DepositAddress.btc_address == deposit_address,
                )
            ).first()
            if not obj:
                return None
            return obj.user.evm_address
