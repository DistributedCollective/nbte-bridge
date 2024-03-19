from dataclasses import dataclass
from bitcointx.core.script import CScript
from bitcointx.wallet import CCoinAddress


TARGET_POSTAGE_SAT = 10_000  # sat locked in rune outputs


@dataclass
class RuneTransfer:
    rune: str
    receiver: str
    amount: int
    postage: int = TARGET_POSTAGE_SAT

    def parse_receiver_address(self) -> CCoinAddress:
        return CCoinAddress(self.receiver)

    def get_receiver_script_pubkey(self) -> CScript:
        return self.parse_receiver_address().to_scriptPubKey()

    def assert_valid(self):
        # TODO: add libbitcoinconsensus validation!
        if not self.rune.isupper() or not self.rune.isalpha():
            raise ValueError("rune must be an uppercase alphabetic string withotu spacers")
        if not isinstance(self.postage, int) or self.postage <= 0:
            raise ValueError("postage must be a positive non-zero integer")
        parsed_address = self.parse_receiver_address()
        if parsed_address is None:
            raise ValueError(f"receiver {self.receiver!r} is not a valid address")
        if not parsed_address.to_scriptPubKey().is_valid():
            raise ValueError(f"receiver {self.receiver!r} does not have a valid scriptPubKey")
