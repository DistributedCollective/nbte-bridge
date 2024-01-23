import requests
from eth_utils import is_checksum_address


class BridgeAPIClient:
    def __init__(self, base_url: str):
        self._base_url = base_url

    def generate_deposit_address(self, evm_address: str) -> str:
        if not is_checksum_address(evm_address):
            raise ValueError(f"Invalid evm_address: {evm_address}")
        response = requests.post(
            self._base_url + "/v1/deposit-addresses/",
            json={
                "evm_address": evm_address,
            },
        )
        response.raise_for_status()
        return response.json()["deposit-address"]
