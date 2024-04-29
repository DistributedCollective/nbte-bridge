from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

import pytest

from bridge.common.ord.multisig import OrdMultisig
from bridge.common.utils import to_base_units
from tests.services.bitcoind import (
    BitcoindService,
    BitcoinWallet,
)
from tests.services.ord import (
    OrdService,
    OrdWallet,
)

logger = logging.getLogger(__name__)
SUPPLY_DECIMAL = Decimal("1000000")
SUPPLY_RAW = to_base_units(SUPPLY_DECIMAL, 18)


class RuneBalanceDict(dict):
    def __add__(self, other: RuneBalanceDict) -> RuneBalanceDict:
        new = RuneBalanceDict(self)
        for rune, amount in other.items():
            new[rune] = new.get(rune, 0) + amount
        return new

    def __sub__(self, other: RuneBalanceDict) -> RuneBalanceDict:
        new = RuneBalanceDict(self)
        for rune, amount in other.items():
            new[rune] = new.get(rune, 0) - amount
        return new


class BalanceTester:
    def __init__(
        self,
        ord: OrdService,  # noqa
        bitcoind: BitcoindService,
    ):
        self._ord = ord
        self._bitcoind = bitcoind

    def get_satoshi_balance(
        self,
        wallet: str | BitcoinWallet | OrdWallet | OrdMultisig,
    ) -> int:
        rpc = self._get_wallet_rpc(wallet)
        return round(rpc.call("getbalance") * Decimal("1e8"))

    def get_rune_balances(
        self,
        wallet: str | BitcoinWallet | OrdWallet | OrdMultisig,
    ) -> RuneBalanceDict:
        self._ord.sync_with_bitcoind()
        rpc = self._get_wallet_rpc(wallet)
        utxos = rpc.listunspent(1, 9999999, [], False)
        rune_balances = defaultdict(int)
        for utxo in utxos:
            txid = utxo["txid"]
            vout = utxo["vout"]
            for i in range(30):
                ord_output = self._ord.api_client.get_output(txid, vout)
                if ord_output["spent"]:
                    break
                if ord_output["indexed"]:
                    break
                time.sleep(i * 0.1)
            else:
                raise ValueError("Output not indexed after 30 tries")
            for rune, entry in ord_output["runes"]:
                rune_balances[rune] += entry["amount"]
        return RuneBalanceDict(dict(rune_balances))

    def get_total_rune_balances(self, wallets: list[str | BitcoinWallet | OrdWallet | OrdMultisig]) -> RuneBalanceDict:
        total_rune_balances = RuneBalanceDict()
        for wallet in wallets:
            total_rune_balances += self.get_rune_balances(wallet)
        return total_rune_balances

    def _get_wallet_rpc(self, wallet: str | BitcoinWallet | OrdWallet | OrdMultisig):
        if isinstance(wallet, str):
            wallet_name = wallet
        else:
            wallet_name = wallet.name
        return self._bitcoind.get_wallet_rpc(wallet_name)


@pytest.fixture(scope="module")
def balance_tester(
    ord: OrdService,  # noqa
    bitcoind: BitcoindService,
) -> BalanceTester:
    return BalanceTester(
        ord=ord,
        bitcoind=bitcoind,
    )


@dataclass
class Setup:
    multisig: OrdMultisig
    runes: list[str]
    funder_wallet: OrdWallet
    user_wallets: list[OrdWallet]
    all_wallet_names: list[str]
    initial_rune_balances: RuneBalanceDict


@pytest.fixture(scope="module")
def setup(
    ord: OrdService,  # noqa A002
    bitcoind: BitcoindService,
    rune_factory,
    multisig_factory,
    root_ord_wallet: OrdWallet,
) -> Setup:
    # We use a 1-of-2 multisig because it simplifies tests, and the PSBT creation logic
    # is unaffected by the number of signers
    multisig, _ = multisig_factory(
        required=1,
        num_signers=2,
    )

    # TODO: don't need funder wallet
    funder_wallet = ord.create_test_wallet("funder")
    user_wallets = [ord.create_test_wallet("user") for _ in range(5)]
    runes = rune_factory(
        "AAAAAA",
        "BBBBBB",
        "CCCCCC",
        "DDDDDD",
        "EEEEEE",
        receiver=multisig.change_address,
        supply=SUPPLY_DECIMAL,
        divisibility=18,
    )

    all_wallet_names = [multisig.name]
    all_wallet_names += [wallet.name for wallet in user_wallets]
    all_wallet_names += [funder_wallet.name]

    initial_rune_balances = RuneBalanceDict()
    for rune in runes:
        initial_rune_balances[rune] = SUPPLY_RAW

    return Setup(
        multisig=multisig,
        runes=runes,
        funder_wallet=funder_wallet,
        user_wallets=user_wallets,
        all_wallet_names=all_wallet_names,
        initial_rune_balances=initial_rune_balances,
    )


@pytest.mark.fuzz
def test_ord_multisig_invariants(
    setup: Setup,
    balance_tester: BalanceTester,
    ord: OrdService,  # noqa
):
    # TODO: implement this
    total_rune_balances_before = balance_tester.get_total_rune_balances(setup.all_wallet_names)
    # multisig_rune_balances_before = balance_tester.get_rune_balances(setup.multisig)
    # multisig_satoshi_balance_before = balance_tester.get_rune_balances(setup.multisig)
    assert total_rune_balances_before == setup.initial_rune_balances
