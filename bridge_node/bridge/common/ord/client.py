from typing import TypedDict, Any
import requests


class OrdApiError(Exception):
    response: requests.Response
    text: str
    status_code: int

    def __init__(self, response: requests.Response):
        self.response = response
        self.text = response.text
        self.status_code = response.status_code
        super().__init__(self.status_code, self.text)


class OrdApiNotFound(OrdApiError):
    pass


class RuneEntry(TypedDict):
    burned: int
    divisibility: int
    etching: str
    mint: Any
    mints: int
    number: int
    rune: str
    spacers: int
    supply: int
    symbol: str
    timestamp: int


class RuneResponse(TypedDict):
    # Example of a RuneResponse
    # {'entry': {'burned': 0, 'divisibility': 18,
    #            'etching': 'a41fc8941069ac2c8c109c533c5d4ff2299ec549bf47e344ece3359600dd0153', 'mint': None, 'mints': 0,
    #            'number': 0, 'rune': 'RUNESAREAWESOME', 'spacers': 0, 'supply': 10000000000000000000000000000, 'symbol': 'R',
    #            'timestamp': 1709917172}, 'id': '103:1', 'parent': None}
    entry: RuneEntry
    id: str
    parent: Any


class OrdApiClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def request(self, method, url, **kwargs):
        headers = kwargs.setdefault("headers", {})
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        resp = requests.request(method, f"{self.base_url}{url}", **kwargs)
        if not resp.ok:
            if resp.status_code == 404:
                raise OrdApiNotFound(resp)
            raise OrdApiError(resp)
        return resp.json()

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def get_rune(self, rune_name: str) -> RuneResponse | None:
        """
        Get rune by name, or None if rune not found
        """
        try:
            return self.get(f"/rune/{rune_name}")
        except OrdApiNotFound:
            return None
