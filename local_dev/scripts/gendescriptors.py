import argparse
import bitcointx
from bridge.common.ord.multisig import OrdMultisig
import json

parser = argparse.ArgumentParser()
parser.add_argument("--network", type=str, choices=["mainnet", "testnet", "regtest"])
parser.add_argument("--xpriv", type=str, required=True)
parser.add_argument(
    "--xpubs", type=str, help="Comma-separated list of xpubs", required=True
)
parser.add_argument("--signers", type=int, required=True)
parser.add_argument("--derivation-path", type=str, default="m/13/0/0")
parser.add_argument("--range", type=int, default=2000)

args = parser.parse_args()

bitcointx.select_chain_params("bitcoin/" + args.network)

xpubs = args.xpubs.split(",")


ms = OrdMultisig(
    master_xpriv=args.xpriv,
    master_xpubs=xpubs,
    num_required_signers=args.signers,
    base_derivation_path=args.derivation_path,
    bitcoin_rpc=None,
    ord_client=None,
)


desc = ms.get_descriptor()
print("Descriptor", desc)

descimport = [
    {
        "desc": desc,
        "range": args.range,
        "timestamp": "now",
    }
]

descimport = "'{}'".format(json.dumps(descimport).replace("'", "\\'"))
print("Command:")
print(
    f"local_dev/bin/bitcoin-cli-testnet -rpcwallet=WALLET importdescriptors {descimport}"
)

print("Change address:", ms.change_address)
