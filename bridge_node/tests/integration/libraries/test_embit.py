from decimal import Decimal

import pytest

from binascii import unhexlify
from io import BytesIO

try:
    from embit import bip32, script
    from embit.transaction import Transaction, TransactionInput, TransactionOutput
    from embit.psbt import PSBT
    from embit.networks import NETWORKS
except ImportError:
    embit = pytest.importorskip("embit")

from ..constants import (
    MULTISIG_XPUBS,
    MULTISIG_XPRVS,
    MULTISIG_ADDRESS,
    MULTISIG_KEY_DERIVATION_PATH,
)
from ..utils import from_satoshi, to_satoshi


@pytest.fixture()
def master_privkeys():
    return [bip32.HDKey.from_string(xprv) for xprv in MULTISIG_XPRVS]


@pytest.fixture()
def master_pubkeys(master_privkeys):
    return [xprv.to_public() for xprv in master_privkeys]


@pytest.fixture()
def child_pubkeys(master_pubkeys):
    ret = [xpub.derive(MULTISIG_KEY_DERIVATION_PATH) for xpub in master_pubkeys]
    ret.sort(key=lambda x: x.key.to_string())
    return ret


@pytest.fixture()
def child_privkeys(master_privkeys):
    ret = [xprv.derive(MULTISIG_KEY_DERIVATION_PATH) for xprv in master_privkeys]
    ret.sort(key=lambda x: x.to_public().key.to_string())
    return ret


@pytest.fixture()
def multisig_redeem_script(child_pubkeys):
    return script.multisig(2, [pubkey.key for pubkey in child_pubkeys])


@pytest.fixture()
def multisig_script(multisig_redeem_script):
    return script.p2wsh(
        multisig_redeem_script,
    )


def test_xprvs_match_pubkeys(master_pubkeys):
    assert [xpub.to_string() for xpub in master_pubkeys] == MULTISIG_XPUBS


def test_derive_multisig_address(multisig_script):
    regtest_address = multisig_script.address(NETWORKS["regtest"])
    assert regtest_address == MULTISIG_ADDRESS


def test_child_privkeys_match_pubkeys(child_privkeys, child_pubkeys):
    assert [c.to_public().key.to_string() for c in child_privkeys] == [
        c.key.to_string() for c in child_pubkeys
    ]


def test_create_psbt(
    multisig_bitcoin_rpc,
    user_bitcoin_rpc,
    multisig_script,
    multisig_redeem_script,
    child_privkeys,
):
    user_btc_before = Decimal(user_bitcoin_rpc.getbalance())
    print("BTC before", user_btc_before)

    utxos = multisig_bitcoin_rpc.call("listunspent", 0, 9999999, [MULTISIG_ADDRESS])
    # utxos = multisig_bitcoin_rpc.listunspent(0, 9999999, [MULTISIG_ADDRESS])
    assert len(utxos) > 0, "Sanity check failed, no utxos to spend"

    amount_btc = Decimal("0.1")
    amount_satoshi = to_satoshi(amount_btc)

    print(utxos[0])

    input_utxos = [utxos[0]]
    print(input_utxos)
    total_amount_in_btc = sum(utxo["amount"] for utxo in input_utxos)
    # total_amount_in_satoshi = sum(utxo['amount'] for utxo in input_utxos)
    # total_amount_in_btc = from_satoshi(total_amount_in_satoshi)
    fee_btc = from_satoshi(1000)
    assert (
        total_amount_in_btc > amount_btc + fee_btc
    ), "Sanity check failed, not enough utxos to cover amount + fee"

    input_txs_raw = [
        multisig_bitcoin_rpc.call("gettransaction", utxo["txid"], True) for utxo in input_utxos
    ]

    change_amount_btc = total_amount_in_btc - amount_btc - fee_btc
    change_amount_satoshi = to_satoshi(change_amount_btc)

    user_address = str(user_bitcoin_rpc.getnewaddress())
    user_script = script.address_to_scriptpubkey(user_address)
    print(user_script)

    user_script.address(NETWORKS["regtest"])
    tx = Transaction(
        vin=[
            TransactionInput(
                # unhexlify(utxo['txid']),
                # utxo['vout'],
                txid=unhexlify(utxo["txid"]),
                vout=utxo["vout"],
            )
            for utxo in input_utxos
        ],
        vout=[
            TransactionOutput(
                amount_satoshi,
                user_script,
            ),
            TransactionOutput(
                change_amount_satoshi,
                multisig_script,
            ),
        ],
    )
    psbt = PSBT(tx)
    for i, input_tx_raw in enumerate(input_txs_raw):
        input_tx = Transaction.read_from(BytesIO(unhexlify(input_tx_raw["hex"])))
        psbt.inputs[i].non_witness_utxo = input_tx
        psbt.inputs[i].redeem_script = multisig_redeem_script
    verified = psbt.verify()
    print(verified)
    print(psbt)
    print(psbt.sign_with(child_privkeys[0]))
    print(psbt)
    print(psbt.sign_with(child_privkeys[1]))
    print(psbt)
