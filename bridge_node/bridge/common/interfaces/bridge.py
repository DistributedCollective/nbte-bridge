from typing import Protocol


class Bridge(Protocol):
    name: str

    def init(self) -> None: ...

    def run_iteration(self) -> None: ...
