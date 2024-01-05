from ..p2p.network import P2PNetwork


class BridgeNode:
    HOST = "0.0.0.0"  # Careful, only use this when running in Docker
    PORT = 5000

    def __init__(self, network: P2PNetwork):
        self.network = network

        self.network.add_listener(self.on_message)

    def on_message(self, msg):
        print("Received message to node: ", msg)

    def __repr__(self):
        return f"<BridgeNode {self.network.URI}>"
