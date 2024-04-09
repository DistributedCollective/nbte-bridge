from bridge.common.p2p.network import Network


class MockNetwork(Network):
    def __init__(self, *, node_id, leader: bool = False):
        self.node_id = node_id
        self._is_leader = leader
        self._listeners = []
        self._answer_callbacks = {}
        self._peers = {}

    def is_leader(self):
        return self._is_leader

    def add_peers(self, peers):
        for peer in peers:
            self._peers[peer.node_id] = peer

    def ask(self, question, **kwargs):
        answers = []

        for peer in self._peers.values():
            answer = peer.answer(question, **kwargs)
            if answer is not None:
                answers.append(answer)

        return answers

    def answer(self, question, **kwargs):
        callback = self._answer_callbacks.get(question, None)

        if callback is not None:
            return callback(**kwargs)

        return None

    def answer_with(self, question, callback):
        self._answer_callbacks[question] = callback

    def broadcast(self, msg):
        for listener in self._listeners:
            listener.receive_message(msg)

    def send(self, to, msg):
        self._peers[to].receive_message(msg)

    def add_listener(self, listener):
        self._listeners.append(listener)
