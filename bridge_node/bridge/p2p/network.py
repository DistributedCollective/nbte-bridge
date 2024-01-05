import Pyro5.api
import threading


class P2PNetwork:
    def __init__(self, node_id, host, port):
        self.daemon = Pyro5.api.Daemon(host=host, port=port)
        self.host = host
        self.port = port
        self.node_id = node_id

        self.uri = self.daemon.register(self, self.node_id)

        if self.node_id is None:
            self.node_id = self.uri.object

        self.peers = self.get_peers()
        self.listeners = []

    def get_peers(self):
        peers = [
            ("rollup-bridge-1", "bridge-node-1"),
            ("rollup-bridge-2", "bridge-node-2"),
            ("rollup-bridge-3", "bridge-node-3"),
        ]

        return [
            Pyro5.api.Proxy(self.get_peer_uri(peer, host))
            for peer, host in peers
            if peer != self.node_id
        ]

    def get_peer_uri(self, peer_id, peer_host):
        return f"PYRO:{peer_id}@{peer_host}:{self.port}"

    def broadcast(self, msg):
        print("Broadcasting to all peers: ", [peer._pyroUri.location for peer in self.peers])

        for peer in self.peers:
            peer.receive(msg)

    @Pyro5.api.expose
    def receive(self, msg):
        print("Forwarding message to listeners: ", msg)

        for listener in self.listeners:
            listener(msg)

    def add_listener(self, listener):
        self.listeners.append(listener)

    def start(self):
        print("Starting daemon loop")
        self.thread = threading.Thread(target=self.daemon.requestLoop)
        self.thread.start()
