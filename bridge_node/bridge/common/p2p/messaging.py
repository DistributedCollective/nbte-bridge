from dataclasses import dataclass
from typing import Any


@dataclass
class MessageEnvelope:
    sender: str
    message: Any
