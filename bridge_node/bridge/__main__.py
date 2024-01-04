from time import sleep
from .core.node import BridgeNode


def main():
    node = BridgeNode()

    while True:
        node.run_iteration()
        sleep(1)


if __name__ == "__main__":
    main()
