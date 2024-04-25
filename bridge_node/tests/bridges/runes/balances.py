from __future__ import annotations

import dataclasses
from decimal import Decimal

from web3.contract import Contract

from bridge.common.ord.client import RuneEntry

from ...services import (
    OrdWallet,
)
from ...services.hardhat import EVMWallet
from ...utils.types import Decimalish


@dataclasses.dataclass
class BalanceSnapshot:
    rune: str
    rune_entry: RuneEntry
    rune_token: Contract
    user_ord_wallet: OrdWallet
    user_evm_wallet: EVMWallet
    user_token_balance_decimal: Decimal
    user_rune_balance_decimal: Decimal
    token_total_supply_decimal: Decimal
    bridge_token_balance_decimal: Decimal
    bridge_rune_balance_decimal: Decimal

    def __add__(self, other: BalanceSnapshot) -> BalanceSnapshot:
        if other.rune != self.rune:
            raise ValueError("Cannot add BalanceSnapshot with different runes")
        if other.rune_token.address != self.rune_token.address:
            raise ValueError("Cannot add BalanceSnapshot with different rune tokens")
        if other.user_ord_wallet.name != self.user_ord_wallet.name:
            raise ValueError("Cannot add BalanceSnapshot with different ord wallets")
        if other.user_evm_wallet.address != self.user_evm_wallet.address:
            raise ValueError("Cannot add BalanceSnapshot with different evm wallets")

        return BalanceSnapshot(
            rune=self.rune,
            rune_entry=self.rune_entry,
            rune_token=self.rune_token,
            user_ord_wallet=self.user_ord_wallet,
            user_evm_wallet=self.user_evm_wallet,
            user_token_balance_decimal=self.user_token_balance_decimal + other.user_token_balance_decimal,
            user_rune_balance_decimal=self.user_rune_balance_decimal + other.user_rune_balance_decimal,
            token_total_supply_decimal=self.token_total_supply_decimal + other.token_total_supply_decimal,
            bridge_token_balance_decimal=self.bridge_token_balance_decimal + other.bridge_token_balance_decimal,
            bridge_rune_balance_decimal=self.bridge_rune_balance_decimal + other.bridge_rune_balance_decimal,
        )

    def __neg__(self) -> BalanceSnapshot:
        return BalanceSnapshot(
            rune=self.rune,
            rune_entry=self.rune_entry,
            rune_token=self.rune_token,
            user_ord_wallet=self.user_ord_wallet,
            user_evm_wallet=self.user_evm_wallet,
            user_token_balance_decimal=-self.user_token_balance_decimal,
            user_rune_balance_decimal=-self.user_rune_balance_decimal,
            token_total_supply_decimal=-self.token_total_supply_decimal,
            bridge_token_balance_decimal=-self.bridge_token_balance_decimal,
            bridge_rune_balance_decimal=-self.bridge_rune_balance_decimal,
        )

    def __sub__(self, other) -> BalanceSnapshot:
        return self + -other

    def assert_values(
        self,
        *,
        user_token_balance_decimal: Decimalish = 0,
        user_rune_balance_decimal: Decimalish = 0,
        token_total_supply_decimal: Decimalish = 0,
        bridge_token_balance_decimal: Decimalish = 0,
        bridge_rune_balance_decimal: Decimalish = 0,
    ):
        """
        Assert multiple balances. Balances not specified as key-word arguments are asserted to equal 0
        """
        self.assert_value("user_token_balance_decimal", user_token_balance_decimal)
        self.assert_value("user_rune_balance_decimal", user_rune_balance_decimal)
        self.assert_value("token_total_supply_decimal", token_total_supply_decimal)
        self.assert_value("bridge_token_balance_decimal", bridge_token_balance_decimal)
        self.assert_value("bridge_rune_balance_decimal", bridge_rune_balance_decimal)

    def assert_value(self, name: str, expected: Decimalish):
        actual = getattr(self, name)
        assert actual == Decimal(expected), f"{name}: {actual} != {expected}"
