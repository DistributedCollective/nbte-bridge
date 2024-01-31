import logging
import requests
from eth_utils import is_checksum_address


logger = logging.getLogger(__name__)


class BridgeAPIClient:
    def __init__(self, base_url: str):
        self._base_url = base_url

    def is_healthy(self) -> bool:
        try:
            response = requests.get(self._base_url + "/api/v1/stats/")
        except requests.exceptions.ConnectionError:
            logger.info("Bridge API is not healthy (ConnectionError)")
            return False
        if response.status_code != 200:
            logger.info("Bridge API is not healthy (status code %s)", response.status_code)
            return False
        try:
            data = response.json()
        except ValueError:
            logger.info("Bridge API is not healthy (invalid JSON: %s)", response.text)
            return False
        healthy = data.get("is_healthy")
        reason = data.get("reason")
        if not healthy:
            logger.info(
                "Bridge API is not healthy (is_healthy: %s, reason: %s)",
                healthy,
                reason,
            )
            return False
        return True

    def generate_deposit_address(self, evm_address: str) -> str:
        if not is_checksum_address(evm_address):
            raise ValueError(f"Invalid evm_address: {evm_address}")
        response = requests.post(
            self._base_url + "/api/v1/deposit-addresses/",
            json={
                "evm_address": evm_address,
            },
        )
        response.raise_for_status()
        return response.json()["deposit_address"]
