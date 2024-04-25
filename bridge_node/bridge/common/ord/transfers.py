import pyord
from bitcointx.core.script import CScript
from bitcointx.wallet import CCoinAddress

TARGET_POSTAGE_SAT = 10_000  # sat locked in rune outputs


class RuneTransfer:
    rune: pyord.Rune
    receiver: str
    amount: int
    postage: int

    def __init__(
        self,
        *,
        rune: pyord.Rune | str | int,
        receiver: str,
        amount: int,
        postage: int = TARGET_POSTAGE_SAT,
    ):
        if isinstance(rune, int):
            rune = pyord.Rune(rune)
        elif isinstance(rune, str):
            rune = pyord.Rune.from_str(rune)
        if not isinstance(rune, pyord.Rune):
            raise ValueError("rune must be a Rune instance, a str or an int")
        self.rune = rune
        self.receiver = receiver
        self.amount = amount
        self.postage = postage

    def parse_receiver_address(self) -> CCoinAddress:
        return CCoinAddress(self.receiver)

    def get_receiver_script_pubkey(self) -> CScript:
        return self.parse_receiver_address().to_scriptPubKey()

    def assert_valid(self):
        if not isinstance(self.postage, int) or self.postage <= 0:
            raise ValueError("postage must be a positive non-zero integer")
        if self.amount == 0:
            raise ValueError("zero transfer amounts are not supported as they have a special meaning in Runes")
        if self.amount <= 0 or not isinstance(self.amount, int):
            raise ValueError(f"invalid amount: {self.amount} (must be a positive integer)")
        parsed_address = self.parse_receiver_address()
        if parsed_address is None:
            raise ValueError(f"receiver {self.receiver!r} is not a valid address")
        if not parsed_address.to_scriptPubKey().is_valid():
            raise ValueError(f"receiver {self.receiver!r} does not have a valid scriptPubKey")
