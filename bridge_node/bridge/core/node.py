from ..p2p.network import Network


class BridgeNode:
    def __init__(self, network: Network):
        self.network = network

        self.network.add_listener(self.on_message)

    def on_message(self, msg):
        print("Received message to node: ", msg)
