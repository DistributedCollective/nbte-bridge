import pytest
from bitcointx.core.key import BIP32Path
from bitcointx.wallet import (
    CCoinExtKey,
    CCoinExtPubKey,
    CBitcoinRegtestExtKey,
    CBitcoinRegtestExtPubKey,
)

import bitcointx

from bridge.btc.derivation import (
    derive_key_for_deposit_address,
    get_derivation_path_for_deposit_address,
    derive_deposit_address_info,
)


XPRVS = [
    "tprv8ZgxMBicQKsPdLiVtqrvinq5JyvByQZs4xWMgzZ3YWK7ndu27yQ3qoWivh8cgdtB3bKuYKWRKhaEvtykaFCsDCB7akNdcArjgrCnFhuDjmV",
    "tprv8ZgxMBicQKsPdMXsXv4Ddkgimo1m89QjXBNUrCgAaDRX5tEDMVA8HotnZmHcMvUVtgh1yXbN74StoJqv76jvRxJmkr2wvkPwTbZb1zeXv3Y",
    "tprv8ZgxMBicQKsPcwXzdBoYKEXmLiBsPzNRfoLadw8WsnmKSHU47fJR3UjAhni8kt5bx5jFG9JZ4oZuxnaX6beTNwc2C5coMHmAvnKpqHA8xVb",
]
XPUBS = [
    "tpubD6NzVbkrYhZ4WokHnVXX8CVBt1S88jkmeG78yWbLxn7Wd89nkNDe2J8b6opP4K38mRwXf9d9VVN5uA58epPKjj584R1rnDDbk6oHUD1MoWD",
    "tpubD6NzVbkrYhZ4WpZfRZip3ALqLpXhHUbe6UyG8iiTzVDuvNUyysyiUJWejtbszZYrDaUM8UZpjLmHyvtV7r1QQNFmTqciAz1fYSYkw28Ux6y",
    "tpubD6NzVbkrYhZ4WQZnWqU8ieBsujhoZKZLF6wMvTApJ4ZiGmipk481DyM2su3y5BDeB9fFLwSmmmsGDGJum79he2fnuQMnpWhe3bGir7Mf4uS",
]


@pytest.fixture(autouse=True, scope="module")
def setup():
    with bitcointx.ChainParams("bitcoin/regtest"):
        yield


@pytest.fixture()
def master_xpubs():
    return [CCoinExtPubKey(xpub) for xpub in XPUBS]


@pytest.fixture()
def master_xprvs():
    return [CCoinExtKey(xpub) for xpub in XPRVS]


# The outputs are locked, because it's rather important that it always returns the same path for the same input
@pytest.mark.parametrize(
    "evm_address,index,expected",
    [
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            0,
            "m/1/6591516/4409781/8787830/3294769/1952256/10128829/36953/0",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            1,
            "m/1/6591516/4409781/8787830/3294769/1952256/10128829/36953/1",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            3,
            "m/1/6591516/4409781/8787830/3294769/1952256/10128829/36953/3",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            100,
            "m/1/6591516/4409781/8787830/3294769/1952256/10128829/36953/100",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            100,
            "m/1/6591516/4409781/8787830/3294769/1952256/10128829/36953/100",
        ),
        (
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            0,
            "m/1/16777215/16777215/16777215/16777215/16777215/16777215/65535/0",
        ),
        (
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            100,
            "m/1/16777215/16777215/16777215/16777215/16777215/16777215/65535/100",
        ),
        ("0x0000000000000000000000000000000000000000", 0, "m/1/0/0/0/0/0/0/0/0"),
        ("0x0000000000000000000000000000000000000000", 100, "m/1/0/0/0/0/0/0/0/100"),
    ],
)
def test_get_derivation_path_for_deposit_address(
    evm_address,
    index,
    expected,
):
    path = get_derivation_path_for_deposit_address(
        evm_address=evm_address,
        index=index,
    )
    assert isinstance(path, BIP32Path)
    assert path[-1] == index  # implementation detail, last part is index. could be skipped
    assert str(path) == expected


# The outputs are locked, because it's rather important that it always returns the same key for the same input
@pytest.mark.parametrize(
    "evm_address,index,expected_pub",
    [
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            0,
            "tpubDQzgLmL7c3wi2taDW8yaqSrDn9jd1oBuybuXv3ZGUfPG7kkSHmuvhu8UfM9xo2onmqTUiD6t7HSmwuPaNi3fszDS4SNEfMZ3oRFKfxjYyFV",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            1,
            "tpubDQzgLmL7c3wi6pPfqDqKpNMhct3Gsq2XsZbVGnstirBdtTs9aTaVSaTKiJ1WPwcgA5FfcRau8R8Spex6wofUEVWBHRUwcG7QFTvJh6AEiZ8",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            3,
            "tpubDQzgLmL7c3wiC4RSLPKod6fxKEgwq1BADGiE4dAnV31tYrQwaDb8d8B434oZv5ZytfKoFR2MxWhE5SVN6LiZcd7aGE3vKsvQpR46QAeFKw8",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            100,
            "tpubDQzgLmL7c3wnSsqqNQ9gCoegGvGnqmqPh3LTtvMo7TkVZJ5aNYqMuCwjr1v8bYY957AcVr7UDGDg3R4R9HDEPy8ZA8Q43USVQV61E9FWthC",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            100,
            "tpubDQzgLmL7c3wnSsqqNQ9gCoegGvGnqmqPh3LTtvMo7TkVZJ5aNYqMuCwjr1v8bYY957AcVr7UDGDg3R4R9HDEPy8ZA8Q43USVQV61E9FWthC",
        ),
        (
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            0,
            "tpubDPeXCU5rr5EQhP7QKofHPfMtG7p2uS6b4w2wJugZ368HAr6JeS5HYZkYMhMFuNuRquGR8sTFoKXvHiACP68PbXtKzSGVUs27QKAW63sAJod",
        ),
        (
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            100,
            "tpubDPeXCU5rr5EV5XtSVeHkByqRyRDu3gb1DPEoKUtyPWdAbogn1wr7mUhit5k4YJW5mfs2U1Q8fLrFGPDwbo46o7zAkYf7UYDigYK9bBrNiCv",
        ),
        (
            "0x0000000000000000000000000000000000000000",
            0,
            "tpubDPVCYak2tRZpABqBrPPiyBuRwWDF3anVPhNFG1ehpWsDAbJcWER9Zmv3e8VNaGQMPmDuqtLK7NLxxoW6LWmWgQ9dqFKHpQN3StNn5gpnJXN",
        ),
        (
            "0x0000000000000000000000000000000000000000",
            100,
            "tpubDPVCYak2tRZtZ1qbJHd44eDWZdf7Ye2U8u6x5RzsX1e9RtSvMPQu1tZkvjh1NSVDaDCAzZgvF2jTaqANNmrmiVje1oBFkRuaEGAUMLySP3N",
        ),
    ],
)
def test_derive_key_for_deposit_address(
    evm_address,
    index,
    expected_pub,
    master_xpubs,
    master_xprvs,
):
    xpub = master_xpubs[0]
    xprv = master_xprvs[0]
    derived_pub = derive_key_for_deposit_address(xpub, evm_address=evm_address, index=index)
    assert isinstance(derived_pub, CCoinExtPubKey)
    assert isinstance(derived_pub, CBitcoinRegtestExtPubKey)
    derived_priv = derive_key_for_deposit_address(xprv, evm_address=evm_address, index=index)
    assert isinstance(derived_priv, CCoinExtKey)
    assert isinstance(derived_priv, CBitcoinRegtestExtKey)
    assert derived_priv.pub == derived_pub.pub
    assert derived_priv.priv.pub == derived_pub.pub
    assert str(derived_pub) != str(xpub)  # catch stupid errors
    assert str(derived_pub) == expected_pub


def test_derive_key_for_deposit_address_all_master_keys(master_xpubs, master_xprvs):
    evm_address = "0x64941c4349b58617763246311DCa009a8dbD9059"
    child_pubs = [derive_key_for_deposit_address(xpub, evm_address, 0).pub for xpub in master_xpubs]
    child_pubs.sort()
    child_privs = [
        derive_key_for_deposit_address(xprv, evm_address, 0).priv for xprv in master_xprvs
    ]
    child_privs.sort(key=lambda x: x.pub)
    assert [c.pub for c in child_privs] == child_pubs


@pytest.mark.parametrize(
    "evm_address,index,expected_deposit_address",
    [
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            0,
            "bcrt1qf99f7nmqzxulvn92lvk0rlvkur0f3fsldg8hd4w8z0ztwddpyx6sdge5ln",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            1,
            "bcrt1qz0k0e4d7pg4prtgrzmc375zq42v6p753ctunl4ksx3nehjdxtdcs4kcr8z",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            3,
            "bcrt1q7453zsa9kelpra7jvgfmuv4j3a9ks4rj2qvdulk87segfzc4fkrqusgcsu",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            100,
            "bcrt1qe844m9uwr5khnkt0tsyl9h7w4zc9g7scu7xkr8s6tmznfd8k693qcs7tnj",
        ),
        (
            "0x64941c4349b58617763246311DCa009a8dbD9059",
            100,
            "bcrt1qe844m9uwr5khnkt0tsyl9h7w4zc9g7scu7xkr8s6tmznfd8k693qcs7tnj",
        ),
        (
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            0,
            "bcrt1qx9c5t425dchwfxl2x3a3zxq9vr6rdxqd7vch045ytf8j52g9rduq969p3f",
        ),
        (
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            100,
            "bcrt1q5x9y8ajtz2eq9zfs2rsrpawyeed42hcelhvwltadcnxptumtzfms4dljew",
        ),
        (
            "0x0000000000000000000000000000000000000000",
            0,
            "bcrt1qr8pj2dekk98k9a7mlvx2s56ajdq6lj9wpzuuvkqqn5hp23zhul7ssd2c3v",
        ),
        (
            "0x0000000000000000000000000000000000000000",
            100,
            "bcrt1q8z68ufq0tsh8axwjt4sncl6zpmzztennk2tgc7a0qvcpcs2ry4xq2ptc72",
        ),
    ],
)
def test_derive_deposit_info(
    evm_address,
    index,
    expected_deposit_address,
    master_xpubs,
):
    info = derive_deposit_address_info(
        master_xpubs=master_xpubs,
        num_required_signers=2,
        evm_address=evm_address,
        index=index,
    )
    assert info.index == index
    assert info.evm_address == evm_address
    assert str(info.derivation_path).startswith("m/1/")
    assert str(info.derivation_path) == str(
        get_derivation_path_for_deposit_address(evm_address, index)
    )
    assert info.btc_deposit_address == expected_deposit_address
