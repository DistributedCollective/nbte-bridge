import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
ABI_DIR = Path(__file__).parent / "abi"


def load_rune_bridge_abi(name: str) -> dict:
    with (ABI_DIR / f"{name}.json").open() as f:
        return json.load(f)
