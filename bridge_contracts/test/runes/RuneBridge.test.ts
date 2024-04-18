import {
    loadFixture,
} from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from 'chai';
import { ethers, upgrades } from "hardhat";
import { getImplementationAddress, getAdminAddress } from '@openzeppelin/upgrades-core';

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
        const runeBridge = await upgrades.deployProxy(
            RuneBridge,
            [
                await accessControl.getAddress(),
                await btcAddressValidator.getAddress(),
            ],
        );

        const runeBridgeAddress = await runeBridge.getAddress();
        console.log("RuneBridge proxy", runeBridgeAddress);
        console.log("Implementation", await getImplementationAddress(ethers.provider, runeBridgeAddress));
        console.log("ProxyAdmin", await getAdminAddress(ethers.provider, runeBridgeAddress));

        return { runeBridge, btcAddressValidator, accessControl };
    }

    it("deploys", async function () {
        const { runeBridge } = await loadFixture(runeBridgeFixture);
        expect(await runeBridge.numRunesRegistered()).to.equal(0);
        expect(await runeBridge.registerRune(
            "Foo",
            "Bar",
            1,
            2
        ));
        expect(await runeBridge.numRunesRegistered()).to.equal(1);
    });
});
