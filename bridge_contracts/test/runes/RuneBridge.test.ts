import {
    loadFixture,
} from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { ethers } from "hardhat";

describe("RuneBridge", function () {
    async function runeBridgeFixture() {
        const NBTEBridgeAccessControl = await ethers.getContractFactory("NBTEBridgeAccessControl");
        const accessControl = await NBTEBridgeAccessControl.deploy();

        const BTCAddressValidator = await ethers.getContractFactory("BTCAddressValidator");
        // add mainnet-compatible config here at first
        const btcAddressValidator = await BTCAddressValidator.deploy(
            await accessControl.getAddress(),
            "bc1",  // bech32 prefix, segwit version not included
            ["1", "3"],  // non-bech32 prefixes
        );

        const RuneBridge = await ethers.getContractFactory("RuneBridge");
        const runeBridge = await RuneBridge.deploy(
            await accessControl.getAddress(),
            await btcAddressValidator.getAddress(),
        );

        return { runeBridge, btcAddressValidator, accessControl };
    }

    it("deploys", async function () {
        await loadFixture(runeBridgeFixture);
    });
});
