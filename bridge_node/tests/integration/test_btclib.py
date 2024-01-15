from decimal import Decimal
import pytest

try:
    from btclib import bip32
    from btclib import script
    from btclib.psbt import Psbt
    from btclib.tx import Tx, TxIn, TxOut, OutPoint
except ImportError:
    btclib = pytest.importorskip("btclib")
from .constants import (
    MULTISIG_XPUBS,
    MULTISIG_XPRVS,
    MULTISIG_ADDRESS,
    MULTISIG_KEY_DERIVATION_PATH,
)
from .utils import from_satoshi, to_satoshi


@pytest.fixture()
def multisig_child_pubkeys():
    ret = [
        bip32.derive(master_pubkey, MULTISIG_KEY_DERIVATION_PATH)
        for master_pubkey in MULTISIG_XPUBS
    ]
    ret.sort(key=lambda x: bip32.BIP32KeyData.b58decode(x).key)
    # print([
    #     bip32.BIP32KeyData.b58decode(x).key.hex()
    #     for x in ret
    # ])
    return ret


@pytest.fixture()
def multisig_child_privkeys():
    ret = [
        bip32.derive(master_privkey, MULTISIG_KEY_DERIVATION_PATH)
        for master_privkey in MULTISIG_XPRVS
    ]
    ret.sort(key=lambda x: bip32.BIP32KeyData.b58decode(bip32.xpub_from_xprv(x)).key)
    # print([
    #     bip32.BIP32KeyData.b58decode(
    #         bip32.xpub_from_xprv(x)
    #     ).key.hex()
    #     for x in ret
    # ])
    return ret


@pytest.fixture()
def multisig_redeem_script(multisig_child_pubkeys):
    return script.ScriptPubKey.p2ms(
        m=2,
        keys=multisig_child_pubkeys,
        network="regtest",
    )


@pytest.fixture()
def multisig_script(multisig_redeem_script):
    return script.ScriptPubKey.p2wsh(
        network="regtest",
        redeem_script=multisig_redeem_script.script,
    )


def test_xprvs_match_pubkeys():
    master_pubkeys = [bip32.xpub_from_xprv(xprv) for xprv in MULTISIG_XPRVS]
    assert master_pubkeys == MULTISIG_XPUBS


def test_derive_multisig_address(multisig_script, multisig_child_privkeys):
    assert multisig_script.address == MULTISIG_ADDRESS


def test_create_psbt(
    multisig_bitcoin_rpc,
    user_bitcoin_rpc,
    multisig_script,
    multisig_redeem_script,
    multisig_child_privkeys,
    multisig_child_pubkeys,
):
    user_btc_before = Decimal(user_bitcoin_rpc.getbalance())
    print("User BTC before", user_btc_before)

    utxos = multisig_bitcoin_rpc.call("listunspent", 0, 9999999, [MULTISIG_ADDRESS])
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

    change_amount_btc = total_amount_in_btc - amount_btc - fee_btc
    change_amount_satoshi = to_satoshi(change_amount_btc)

    user_address = str(user_bitcoin_rpc.getnewaddress())
    user_script = script.ScriptPubKey.from_address(user_address)

    input_txs_raw = [
        multisig_bitcoin_rpc.call("gettransaction", utxo["txid"], True) for utxo in input_utxos
    ]

    tx = Tx(
        vin=[
            TxIn(
                prev_out=OutPoint(
                    tx_id=utxo["txid"],
                    vout=utxo["vout"],
                )
            )
            for utxo in input_utxos
        ],
        vout=[
            TxOut(
                value=amount_satoshi,
                script_pub_key=user_script,
            ),
            TxOut(
                value=change_amount_satoshi,
                script_pub_key=multisig_script,
            ),
        ],
    )
    print(tx)
    psbt = Psbt.from_tx(tx)
    print(psbt)
    for i, input_tx_raw in enumerate(input_txs_raw):
        input_tx = Tx.parse(input_tx_raw["hex"])
        psbt.inputs[i].non_witness_utxo = input_tx
        psbt.inputs[i].redeem_script = multisig_redeem_script.script
    psbt.assert_valid()
    psbt.assert_signable()

    # TODO: make the signatures work
    for privkey, pubkey in zip(multisig_child_privkeys[:2], multisig_child_pubkeys):
        for psbt_in in psbt.inputs:
            pass

    pass
