"""
Quick and dirty testserver for UI dev
"""
import logging
import sys
from bridge.common.btc.rpc import BitcoinRPC

sys.path.extend("bridge_node")
from tests.integration.fixtures.harness import IntegrationTestHarness  # noqa
from tests import services  # noqa

WATCHED_CONTAINERS = [
    "alice-bridge",
    "bob-bridge",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
RUNE_BRIDGE_ADDRESS = "0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9"
RUNE_NAME = "MYRUNEISGOODER"
BTC_SLEEP_TIME = 5


def create_user_ord():
    service = services.OrdService(
        service="user-ord",
    )
    assert service.is_started()
    return service


def create_alice_ord():
    service = services.OrdService(
        service="alice-ord",
    )
    assert service.is_started()
    return service


def create_alice_ord_wallet(alice_ord, bitcoin_rpc):
    wallet = services.OrdWallet(
        ord=alice_ord,
        name="alice-ord-test",
    )
    wallets = bitcoin_rpc.call("listwallets")
    if wallet.name not in wallets:
        logger.info("Creating alice-ord-test wallet")
        wallet.create()

    balances = wallet.cli("balance")
    if balances["cardinal"] < 100:
        logger.info("Funding alice-ord-test wallet")
        address = wallet.cli("receive")["address"]
        logger.info("ALICE ORD ADDRESS: %s", address)
        bitcoin_rpc.mine_blocks(101, address, sleep=BTC_SLEEP_TIME)

    if RUNE_NAME not in balances["runes"]:
        wallet.cli(
            "etch",
            "--divisibility",
            "18",
            "--fee-rate",
            "1",
            "--rune",
            RUNE_NAME,
            "--supply",
            "10000000000",
            "--symbol",
            "R",
        )
        bitcoin_rpc.mine_blocks(1, sleep=BTC_SLEEP_TIME)

    return wallet


def create_user_ord_wallet(user_ord, bitcoin_rpc, alice_ord_wallet):
    wallet = services.OrdWallet(
        ord=user_ord,
        name="user-ord-test",
    )
    wallets = bitcoin_rpc.call("listwallets")
    address = None
    if wallet.name not in wallets:
        logger.info("Creating user-ord-test wallet")
        wallet.create()

    balances = wallet.cli("balance")
    if balances["cardinal"] < 1000:
        logger.info("Funding user-ord-test wallet")
        address = wallet.cli("receive")["address"]
        logger.info("USER ORD ADDRESS: %s", address)
        bitcoin_rpc.mine_blocks(101, address, sleep=BTC_SLEEP_TIME)

    if balances["runes"].get(RUNE_NAME, 0) < 1000 * 10**18:
        if address is None:
            address = wallet.cli("receive")["address"]
            logger.info("USER ORD ADDRESS: %s", address)
        alice_ord_wallet.cli(
            "send",
            "--fee-rate",
            "1",
            address,
            f"100000 {RUNE_NAME}",
        )
        bitcoin_rpc.mine_blocks(1, sleep=BTC_SLEEP_TIME)

    return wallet


def init_runes():
    bitcoin_rpc = BitcoinRPC("http://polaruser:polarpass@localhost:18443")
    alice_ord = create_alice_ord()
    user_ord = create_user_ord()
    alice_ord_wallet = create_alice_ord_wallet(alice_ord, bitcoin_rpc)
    create_user_ord_wallet(user_ord, bitcoin_rpc, alice_ord_wallet)


def print_info():
    print("")
    print("[INFO]")
    print("Hardhat network (for metamask, etc): http://localhost:18545")
    print("ORD explorer:                        http://localhost:3080/runes")
    print("Bridge API:                          http://localhost:8181")
    print(f"RuneBridge contract                  {RUNE_BRIDGE_ADDRESS}")
    print(f"Test rune name:                      {RUNE_NAME}")
    print("")
    print("To generate a deposit address:")
    print(
        """
    curl -X POST -H 'Content-Type: application/json' -d '{"evm_address": "0x1111111111111111111111111111111111111111"}' http://localhost:8181/api/v1/runes/deposit-addresses/
    """
    )
    print("To read balances of the user")
    print(
        """
    local_dev/bin/user-ord wallet balance
    """
    )
    print("To send runes to the address:")
    print(
        f"""
    local_dev/bin/user-ord wallet send --fee-rate 1 bcrt1qtxysk2megp39dnpw9va32huk5fesrlvutl0zdpc29asar4hfkrlqs2kzv5 "123 {RUNE_NAME}"
    """
    )


def main():
    harness = IntegrationTestHarness(verbose=True)
    try:
        harness.start()

        print("Harness started, initing runes")
        init_runes()

        print_info()

        print("Press [enter] to view logs or Ctrl-C to quit")
        input()
        harness._run_docker_compose_command("logs", "-f", *WATCHED_CONTAINERS)
    except KeyboardInterrupt:
        print("Stopping")
    finally:
        harness.stop()


if __name__ == "__main__":
    main()
