from typing import cast
import pathlib
from eth_typing import ChecksumAddress

# __base__/bridge_node/tests/integration
INTEGRATION_TEST_DIR = pathlib.Path(__file__).parent
PROJECT_BASE_DIR = INTEGRATION_TEST_DIR.parent.parent.parent

WEB3_RPC_URL = "http://localhost:18545"
MULTISIG_BITCOIN_RPC_URL = "http://bridgebtc:hunter3@localhost:18443/wallet/multisig"
USER_BITCOIN_RPC_URL = "http://bridgebtc:hunter3@localhost:18443/wallet/user"
BRIDGE_CONTRACT_ADDRESS = cast(ChecksumAddress, "0x5FbDB2315678afecb367f032d93F642f64180aa3")

MULTISIG_XPRVS = [
    "tprv8ZgxMBicQKsPdLiVtqrvinq5JyvByQZs4xWMgzZ3YWK7ndu27yQ3qoWivh8cgdtB3bKuYKWRKhaEvtykaFCsDCB7akNdcArjgrCnFhuDjmV",
    "tprv8ZgxMBicQKsPdMXsXv4Ddkgimo1m89QjXBNUrCgAaDRX5tEDMVA8HotnZmHcMvUVtgh1yXbN74StoJqv76jvRxJmkr2wvkPwTbZb1zeXv3Y",
    "tprv8ZgxMBicQKsPcwXzdBoYKEXmLiBsPzNRfoLadw8WsnmKSHU47fJR3UjAhni8kt5bx5jFG9JZ4oZuxnaX6beTNwc2C5coMHmAvnKpqHA8xVb",
]
MULTISIG_XPUBS = [
    "tpubD6NzVbkrYhZ4WokHnVXX8CVBt1S88jkmeG78yWbLxn7Wd89nkNDe2J8b6opP4K38mRwXf9d9VVN5uA58epPKjj584R1rnDDbk6oHUD1MoWD",
    "tpubD6NzVbkrYhZ4WpZfRZip3ALqLpXhHUbe6UyG8iiTzVDuvNUyysyiUJWejtbszZYrDaUM8UZpjLmHyvtV7r1QQNFmTqciAz1fYSYkw28Ux6y",
    "tpubD6NzVbkrYhZ4WQZnWqU8ieBsujhoZKZLF6wMvTApJ4ZiGmipk481DyM2su3y5BDeB9fFLwSmmmsGDGJum79he2fnuQMnpWhe3bGir7Mf4uS",
]
MULTISIG_KEY_DERIVATION_PATH = "m/0/0/0"
MULTISIG_ADDRESS = "bcrt1qtxysk2megp39dnpw9va32huk5fesrlvutl0zdpc29asar4hfkrlqs2kzv5"

NODE1_API_BASE_URL = "http://localhost:8081"
