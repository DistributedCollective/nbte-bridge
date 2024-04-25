import pathlib
from typing import cast

from eth_typing import ChecksumAddress

# __base__/bridge_node/tests/integration
INTEGRATION_TEST_DIR = pathlib.Path(__file__).parent
PROJECT_BASE_DIR = INTEGRATION_TEST_DIR.parent.parent.parent

WEB3_RPC_URL = "http://localhost:18545"
USER_BITCOIN_RPC_URL = "http://polaruser:polarpass@localhost:18443"
BRIDGE_CONTRACT_ADDRESS = cast(ChecksumAddress, "0x5FbDB2315678afecb367f032d93F642f64180aa3")
ALICE_EVM_PRIVATE_KEY = "0x9a9a640da1fc0181e43a9ea00b81878f26e1678e3e246b25bd2835783f2be181"
BOB_EVM_PRIVATE_KEY = "0x034262349de8b7bb1d8fdd7a9b6096aae0906a8f3b58ecc31af58b9f9a30e567"

NODE1_API_BASE_URL = "http://localhost:8181"
