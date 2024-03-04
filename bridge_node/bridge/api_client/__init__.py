import logging
import requests


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

    def generate_tap_deposit_address(
        self,
        rsk_address,
        *,
        tap_asset_id: str = None,
        tap_amount: int = None,
        rsk_token_address: str = None,
        rsk_amount: int = None,
    ) -> str:
        response = requests.post(
            self._base_url + "/api/v1/tap/deposit-addresses/",
            json={
                "tap_asset_id": tap_asset_id,
                "tap_amount": tap_amount,
                "rsk_address": rsk_address,
                "rsk_token_address": rsk_token_address,
                "rsk_amount": rsk_amount,
            },
        )
        response.raise_for_status()
        return response.json()["deposit_address"]

    def get_transfers(
        self,
        address: str,
        transfer_type: str,
    ):
        part = "tap" if transfer_type == "tap_to_rsk" else "rsk"

        response = requests.post(
            self._base_url + "/api/v1/" + part + "/transfers/",
            json={
                "address": address,
            },
        )

        response.raise_for_status()
        return response.json()["transfers"]

    def generate_rune_deposit_address(
        self,
        evm_address,
    ) -> str:
        response = requests.post(
            self._base_url + "/api/v1/runes/deposit-addresses/",
            json={
                "evm_address": evm_address,
            },
        )
        response.raise_for_status()
        return response.json()["deposit_address"]
