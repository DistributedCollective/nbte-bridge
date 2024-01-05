import logging

from ..p2p.network import Network


class BridgeNode:
    def __init__(self, network: Network):
        self.network = network

        self.network.add_listener(self.on_message)

        self.ping()

    def on_message(self, msg):
        logging.debug(f"Received message to node: {msg}")

        if msg == "Ping":
            self.network.broadcast("Pong")

    def ping(self):
        self.network.broadcast("Ping")
