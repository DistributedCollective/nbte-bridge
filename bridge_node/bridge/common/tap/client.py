import dataclasses
import pathlib
from typing import Union, TypedDict, Any
import urllib.parse

import requests


DEFAULT_ASSET_VERSION = "ASSET_VERSION_V0"


class AssetGenesisDict(TypedDict):
    genesis_point: str
    name: str
    meta_hash: str
    asset_id: str
    asset_type: str
    output_index: int
    version: int


class ChainAnchorDict(TypedDict):
    anchor_tx: str
    anchor_block_hash: str
    anchor_outpoint: str
    internal_key: str
    merkle_root: str
    block_height: int


class AssetDict(TypedDict):
    version: str
    asset_genesis: AssetGenesisDict
    amount: str
    lock_time: int
    relative_lock_time: int
    script_version: int
    script_key: str
    script_key_is_local: bool
    asset_group: Any
    chain_anchor: ChainAnchorDict
    prev_witnesses: list
    is_spent: bool
    lease_owner: str
    lease_expiry: int
    is_burn: bool


class KeyLocDict(TypedDict):
    key_family: int
    key_index: int


class KeyDescDict(TypedDict):
    raw_key_bytes: str
    key_loc: KeyLocDict


class ScriptKeyDict(TypedDict):
    pub_key: str
    key_desc: KeyDescDict
    tap_tweak: str


class ProofDict(TypedDict):
    raw_proof_file: str
    genesis_point: str


class Asset:
    def __init__(self, asset_dict: AssetDict):
        self.asset_dict = asset_dict

    @property
    def name(self):
        return self.asset_dict["asset_genesis"]["name"]

    @property
    def asset_id(self):
        return self.asset_dict["asset_genesis"]["asset_id"]

    def __repr__(self):
        return f"Asset(name={self.name!r}, asset_id={self.asset_id!r})"


@dataclasses.dataclass()
class CreateAddressResponse:
    address: str
    asset_id: str
    amount: int
    group_key: str
    script_key: ScriptKeyDict
    internal_key: KeyDescDict
    tapscript_sibling: str
    taproot_output_key: str
    proof_courier_addr: str
    asset_version: str


class AddrDict(TypedDict):
    encoded: str
    asset_id: str
    asset_type: str
    amount: int
    group_key: str
    script_key: str
    internal_key: str
    tapscript_sibling: str
    taproot_output_key: str
    proof_courier_addr: str
    asset_version: str


class AddrEventDict(TypedDict):
    creation_time_unix_seconds: int
    addr: AddrDict
    status: str
    outpoint: str
    utxo_amt_sat: int
    taproot_sibling: str
    confirmation_height: int
    has_proof: bool


class ListReceivesDict(TypedDict):
    events: list[AddrEventDict]


class TapRestError(requests.HTTPError):
    def __init__(self, response: requests.Response):
        super().__init__(
            f"{response.status_code} {response.reason}: {response.text}",
            response=response,
        )


class TapRestClient:
    # Public universe host helps with syncing things in tests
    public_universe_host: str | None

    def __init__(
        self,
        *,
        rest_host: str,
        macaroon_path: Union[pathlib.Path, str],
        tls_cert_path: Union[pathlib.Path, str],
        public_universe_host: str = None,
    ):
        self.public_universe_host = public_universe_host
        self._rest_host = rest_host
        self._macaroon_path = macaroon_path
        self._tls_cert_path = tls_cert_path
        self._macaroon = pathlib.Path(macaroon_path).read_bytes().hex()
        self._base_url = f"https://{rest_host}/v1/taproot-assets/"

    def request(
        self,
        method: str,
        path: str,
        data: Union[dict, None] = None,
        query: Union[dict, None] = None,
    ):
        if path.startswith("/"):
            path = path[1:]
        url = f"{self._base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Grpc-Metadata-macaroon": self._macaroon}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        r = requests.request(
            method,
            url,
            headers=headers,
            json=data,
            verify=str(self._tls_cert_path),
        )
        try:
            r.raise_for_status()
        except Exception as e:
            raise TapRestError(response=r) from e
        return r.json()

    def get(self, path: str, query: Union[dict, None] = None):
        return self.request("GET", path, query=query)

    def post(self, path: str, data: dict = None, *, query: Union[dict, None] = None):
        return self.request("POST", path, data=data, query=query)

    def put(self, path: str, data: dict = None, *, query: Union[dict, None] = None):
        return self.request("PUT", path, data=data, query=query)

    def delete(self, path: str, *, query: Union[dict, None] = None):
        return self.request("DELETE", path, query=query)

    # Derived methods, should have their own class probably
    # =====================================================

    def get_balances_by_asset_id(self) -> dict[str, int]:
        response = self.get("/assets/balance", {"asset_id": 1})
        return {asset_id: int(d["balance"]) for asset_id, d in response["asset_balances"].items()}

    def get_asset_balance(self, asset_id: str) -> int:
        return self.get_balances_by_asset_id().get(asset_id, 0)

    def send_assets(self, *tap_addresses: str):
        return self.post(
            "/send",
            {
                "tap_addrs": tap_addresses,
            },
        )

    def mint_asset(
        self,
        *,
        name: str = "Foo",
        amount: int = 1000,
        asset_version: str = DEFAULT_ASSET_VERSION,
        asset_type: str = "NORMAL",
        finalize: bool = True,
    ) -> Asset:
        mint_response = self.post(
            "/assets",
            {
                "asset": {
                    "asset_version": asset_version,
                    "asset_type": asset_type,
                    "name": name,
                    "amount": amount,
                }
            },
        )
        # {'pending_batch': {'batch_key': '022ef230f4c15ff544b9e49ff4695006811d4029e7d31254bedab1af15c18528f2',
        #                    'batch_txid': '', 'state': 'BATCH_STATE_PENDING', 'assets': [
        #         {'asset_version': 'ASSET_VERSION_V0', 'asset_type': 'NORMAL', 'name': 'BobDollar', 'asset_meta': None,
        #          'amount': '1000', 'new_grouped_asset': False, 'group_key': '', 'group_anchor': ''}]}}
        # pending_batch = mint_response['pending_batch']
        batch_key = mint_response["pending_batch"]["batch_key"]
        if finalize:
            self.finalize_minting_batch()
        candidates = [
            a
            for a in self.list_assets()
            if a.name == name and a.asset_dict["chain_anchor"]["internal_key"] == batch_key
        ]
        if len(candidates) != 1:
            raise ValueError(f"Expected 1 candidate, got {len(candidates)}")
        return candidates[0]

    def finalize_minting_batch(self):
        finalize_response = self.post("/assets/mint/finalize")
        # {'batch': {'batch_key': '022ef230f4c15ff544b9e49ff4695006811d4029e7d31254bedab1af15c18528f2',
        #            'batch_txid': '7da930defb6386c8475f2044edd1f9f47cb798b234bdb716cf2d6bfd570632ff',
        #            'state': 'BATCH_STATE_BROADCAST', 'assets': [
        #         {'asset_version': 'ASSET_VERSION_V0', 'asset_type': 'NORMAL', 'name': 'BobDollar', 'asset_meta': None,
        #          'amount': '1000', 'new_grouped_asset': False, 'group_key': '', 'group_anchor': ''}]}}
        return finalize_response["batch"]

    def list_assets(self) -> list[Asset]:
        return [Asset(d) for d in self.get("/assets")["assets"]]

    def next_script_key(self, key_family: int = 212) -> ScriptKeyDict:
        return self.post("/wallet/script-key/next", {"key_family": key_family})["script_key"]

    def next_internal_key(self, key_family: int = 212) -> KeyDescDict:
        return self.post("/wallet/internal-key/next", {"key_family": key_family})["internal_key"]

    def create_address(
        self,
        *,
        asset_id: str,
        amount: int,
        script_key: ScriptKeyDict | None = None,
        internal_key: KeyDescDict | None = None,
    ) -> CreateAddressResponse:
        if script_key is None:
            script_key = self.next_script_key()
        if internal_key is None:
            internal_key = self.next_internal_key()
        response = self.post(
            "/addrs",
            {
                "asset_id": asset_id,
                "amt": amount,
                "script_key": script_key,
                "internal_key": internal_key,
                "asset_version": DEFAULT_ASSET_VERSION,
            },
        )
        return CreateAddressResponse(
            address=response["encoded"],
            asset_id=response["asset_id"],
            amount=int(response["amount"]),
            script_key=script_key,
            internal_key=internal_key,
            group_key=response["group_key"],
            tapscript_sibling=response["tapscript_sibling"],
            taproot_output_key=response["taproot_output_key"],
            proof_courier_addr=response["proof_courier_addr"],
            asset_version=response["asset_version"],
        )

    def list_receives(self, *, address: str = None, status: str = None) -> ListReceivesDict:
        body = {}
        if address is not None:
            body["filter_addr"] = address
        if status is not None:
            body["filter_status"] = status
        return self.post("/addrs/receives", body)

    def export_proof(self, asset_id: str, script_key_pubkey: str) -> ProofDict:
        return self.post(
            "/proofs/export",
            {
                "asset_id": asset_id,
                "script_key": script_key_pubkey,
            },
        )

    def sync_universe(
        self,
        universe_host: str,
        *,
        #
        issuance_only: bool = False,
        # TODO: figure out how to get asset_ids/sync_targets working
        # asset_ids: list[str] | None = None,
    ):
        body = {
            "universe_host": universe_host,
            "sync_mode": "SYNC_ISSUANCE_ONLY" if issuance_only else "SYNC_FULL",
        }
        # TODO: figure out how to get sync_targets working
        # if asset_ids is not None:
        #     body['sync_targets'] = [
        #         {'id': {
        #             'asset_id_str': asset_id,
        #             'proof_type': 'PROOF_TYPE_UNSPECIFIED',
        #         }}
        #         for asset_id in asset_ids
        #     ]
        return self.post("/universe/sync", body)

    def list_asset_utxos(self, asset_id):
        utxos_response = self.get("/assets/utxos")
        utxos_by_outpoint = utxos_response["managed_utxos"]
        asset_utxos = {}
        for key, value in utxos_by_outpoint.items():
            assert len(value["assets"]) == 1
            asset = value["assets"][0]
            genesis = asset["asset_genesis"]
            if genesis["asset_id"] != asset_id:
                continue
            asset_utxos[key] = value
        return asset_utxos
