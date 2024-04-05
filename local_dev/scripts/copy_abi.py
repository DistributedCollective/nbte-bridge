"""
Copy abis from hardhat
"""
import json
import pathlib
import subprocess
import argparse
import warnings

ROOT_DIR = pathlib.Path(__file__).parent.parent.parent.absolute()
BRIDGE_NODE_DIR = ROOT_DIR / "bridge_node"
BRIDGE_CONTRACTS_DIR = ROOT_DIR / "bridge_contracts"


def copy_abis_from_dir(python_dir: pathlib.Path, hardhat_dir: pathlib.Path):
    print(f"Copying ABIs from {hardhat_dir} to {python_dir}")
    existing_abis = {p.stem for p in python_dir.iterdir()}
    for path in hardhat_dir.iterdir():
        # Test that it's a directory and ends in .sol
        if not path.is_dir() or path.suffix != ".sol":
            continue
        python_path = python_dir / f"{path.stem}.json"
        if path.stem in existing_abis:
            print(f"Overwriting {python_path}")
            existing_abis.remove(path.stem)
        else:
            print(f"Copying new ABI {python_path}")

        hardhat_json_path = path / f"{path.stem}.json"
        with open(hardhat_json_path) as f:
            abi = json.load(f)["abi"]

        with open(python_path, "w") as f:
            json.dump(abi, f, indent="    ")
            f.write("\n")

    if existing_abis:
        warnings.warn(
            f"Found ABIs that are in {python_dir} but not in hardhat: {existing_abis}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-compile", action="store_true")
    args = parser.parse_args()

    if not args.no_compile:
        print("Compiling hardhat contracts")
        subprocess.run(
            ["npx", "hardhat", "compile"],
            cwd=BRIDGE_CONTRACTS_DIR,
            check=True,
        )

    copy_abis_from_dir(
        python_dir=BRIDGE_NODE_DIR / "bridge" / "bridges" / "runes" / "abi",
        hardhat_dir=BRIDGE_CONTRACTS_DIR / "artifacts" / "contracts" / "runes",
    )
    # copy_abis_from_dir(
    #     python_dir=BRIDGE_NODE_DIR / "bridge" / "common" / "evm" / "abi" / "shared",
    #     hardhat_dir=BRIDGE_CONTRACTS_DIR / "artifacts" / "contracts" / "shared",
    # )


if __name__ == "__main__":
    main()
