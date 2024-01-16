import pytest
from bridge.btc.multisig import BitcoinMultisig
from bridge.btc.types import UTXO, PSBT, Transfer
from ..constants import (
    MULTISIG_ADDRESS,
    MULTISIG_KEY_DERIVATION_PATH,
    MULTISIG_XPUBS,
    MULTISIG_XPRVS,
)


def make_multisig(multisig_bitcoin_rpc, xprv):
    return BitcoinMultisig(
        bitcoin_rpc=multisig_bitcoin_rpc,
        key_derivation_path=MULTISIG_KEY_DERIVATION_PATH,
        master_xpubs=MULTISIG_XPUBS,
        master_xpriv=xprv,
        num_required_signers=2,
    )


@pytest.fixture()
def multisig(multisig_bitcoin_rpc) -> BitcoinMultisig:
    return make_multisig(multisig_bitcoin_rpc, MULTISIG_XPRVS[0])


@pytest.fixture()
def multisig_2(multisig_bitcoin_rpc) -> BitcoinMultisig:
    return make_multisig(multisig_bitcoin_rpc, MULTISIG_XPRVS[1])


@pytest.fixture()
def multisig_3(multisig_bitcoin_rpc) -> BitcoinMultisig:
    return make_multisig(multisig_bitcoin_rpc, MULTISIG_XPRVS[2])


def test_multisig_address(multisig: BitcoinMultisig):
    assert multisig._multisig_address == MULTISIG_ADDRESS


def test_list_utxos(multisig: BitcoinMultisig):
    utxos = multisig._list_utxos()
    assert len(utxos) > 0
    assert all(isinstance(utxo, UTXO) for utxo in utxos)
    assert all(utxo.address == MULTISIG_ADDRESS for utxo in utxos)
    assert utxos == list(sorted(utxos, key=lambda utxo: utxo.confirmations, reverse=True))


def test_construct_psbt(multisig: BitcoinMultisig):
    psbt = multisig.construct_psbt(
        transfers=[
            Transfer(
                recipient_address=MULTISIG_ADDRESS,
                amount_satoshi=100_000,
            )
        ]
    )
    assert isinstance(psbt, PSBT)
