from decimal import Decimal
from binascii import unhexlify
from io import BytesIO

import bitcointx
import pytest
from bitcointx import segwit_addr
from bitcointx.core.key import BIP32PathTemplate, KeyStore
from bitcointx.core.script import standard_multisig_redeem_script
from bitcointx.wallet import CCoinExtKey, CCoinExtPubKey, P2WSHBitcoinAddress, CCoinAddress
from bitcointx.core.psbt import PartiallySignedBitcoinTransaction
from bitcointx.core import CTransaction, CTxIn, CTxOut, COutPoint

from ..constants import (
    MULTISIG_ADDRESS,
    MULTISIG_KEY_DERIVATION_PATH,
    MULTISIG_XPRVS,
    MULTISIG_XPUBS,
)
from ..utils import from_satoshi, to_satoshi, wait_for_condition

bitcointx.select_chain_params("bitcoin/regtest")


@pytest.fixture()
def master_xpubs():
    return [CCoinExtPubKey(xpub) for xpub in MULTISIG_XPUBS]


@pytest.fixture()
def master_xprvs():
    return [CCoinExtKey(xpub) for xpub in MULTISIG_XPRVS]


@pytest.fixture()
def derivation_path_template():
    return BIP32PathTemplate(MULTISIG_KEY_DERIVATION_PATH)


@pytest.fixture()
def child_xpubs(master_xpubs, derivation_path_template):
    ret = [xpub.derive(0).derive(0).derive(0) for xpub in master_xpubs]
    ret.sort(key=lambda x: x.pub)
    return ret


@pytest.fixture()
def child_xprvs(master_xprvs, derivation_path_template):
    ret = [xprv.derive(0).derive(0).derive(0) for xprv in master_xprvs]
    ret.sort(key=lambda x: x.pub)
    return ret


@pytest.fixture()
def multisig_redeem_script(child_xpubs):
    return standard_multisig_redeem_script(
        total=3, required=2, pubkeys=[xpub.pub for xpub in child_xpubs]
    )


@pytest.fixture()
def multisig_script(multisig_redeem_script):
    return P2WSHBitcoinAddress.from_redeemScript(multisig_redeem_script)


def test_xprvs_match_pubkeys(master_xpubs, master_xprvs):
    assert [xpub.pub for xpub in master_xpubs] == [xprv.pub for xprv in master_xprvs]


def test_derive_multisig_address(multisig_script):
    assert segwit_addr.encode("bcrt", 0, multisig_script) == MULTISIG_ADDRESS


def test_psbt(
    multisig_bitcoin_rpc,
    user_bitcoin_rpc,
    multisig_script,
    multisig_redeem_script,
    master_xprvs,
    child_xprvs,
    child_xpubs,
):
    user_btc_before = Decimal(user_bitcoin_rpc.getbalance())

    utxos = multisig_bitcoin_rpc.call("listunspent", 0, 9999999, [MULTISIG_ADDRESS])
    assert len(utxos) > 0, "Sanity check failed, no utxos to spend"

    amount_btc = Decimal("0.1")
    amount_satoshi = to_satoshi(amount_btc)

    input_utxos = [utxos[0]]
    total_amount_in_btc = sum(utxo["amount"] for utxo in input_utxos)
    fee_btc = from_satoshi(1000)
    assert (
        total_amount_in_btc > amount_btc + fee_btc
    ), "Sanity check failed, not enough utxos to cover amount + fee"

    change_amount_btc = total_amount_in_btc - amount_btc - fee_btc
    change_amount_satoshi = to_satoshi(change_amount_btc)

    user_address = str(user_bitcoin_rpc.getnewaddress())
    user_address_parsed = CCoinAddress(user_address)
    user_script_pubkey = user_address_parsed.to_scriptPubKey()

    input_txs_raw = [
        multisig_bitcoin_rpc.call("gettransaction", utxo["txid"], True) for utxo in input_utxos
    ]

    unsigned_tx = CTransaction(
        vin=[
            CTxIn(
                prevout=COutPoint(
                    hash=unhexlify(input_utxo["txid"])[::-1],
                    n=input_utxo["vout"],
                ),
            )
            for input_utxo in input_utxos
        ],
        vout=[
            CTxOut(
                nValue=amount_satoshi,
                scriptPubKey=user_script_pubkey,
            ),
            CTxOut(
                nValue=change_amount_satoshi,
                scriptPubKey=multisig_script.to_scriptPubKey(),
            ),
        ],
    )
    psbt = PartiallySignedBitcoinTransaction(
        unsigned_tx=unsigned_tx,
    )
    for i, psbt_input in enumerate(psbt.inputs):
        psbt_input.witness_script = multisig_redeem_script
        input_tx = input_txs_raw[i]
        psbt.set_utxo(
            index=i,
            utxo=CTransaction.stream_deserialize(BytesIO(unhexlify(input_tx["hex"]))),
            force_witness_utxo=True,
        )

    # Did not get this working but it could be cool
    # keystore = KeyStore.from_iterable(
    #     master_xprvs,
    #     default_path_template=BIP32PathTemplate(MULTISIG_KEY_DERIVATION_PATH),
    #     require_path_templates=True
    # )
    keystore = KeyStore.from_iterable([p.priv for p in child_xprvs])
    result = psbt.sign(
        keystore,
    )
    assert result.inputs_info[0].num_new_sigs == 2
    assert result.inputs_info[0].num_sigs_missing == 0
    assert result.is_final
    assert result.is_ready

    extracted_tx = psbt.extract_transaction()
    extracted_tx_hex = extracted_tx.serialize().hex()
    # print(extracted_tx_hex)
    accept_result = multisig_bitcoin_rpc.call("testmempoolaccept", [extracted_tx_hex])
    # print(accept_result)
    assert accept_result[0]["allowed"], accept_result[0].get("reject-reason")

    multisig_bitcoin_rpc.sendrawtransaction(extracted_tx_hex)

    user_btc_after = wait_for_condition(
        callback=lambda: Decimal(user_bitcoin_rpc.getbalance()),
        condition=lambda balance: balance != user_btc_before,
        description="user BTC balance change",
    )
    assert user_btc_after == user_btc_before + amount_btc
