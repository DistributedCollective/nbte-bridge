import {loadFixture} from "@nomicfoundation/hardhat-toolbox/network-helpers";
import {ethers} from "hardhat";
import {expect} from 'chai';
import {RuneToken} from '../../typechain-types';


interface DeployArgs {
    tokenName: string;
    tokenSymbol: string;
    rune: number;
    runeDivisibility: number;
}

describe("RuneToken", function () {
    async function deploy({
        tokenName,
        tokenSymbol,
        rune,
        runeDivisibility,
    }: DeployArgs) {
        const RuneToken = await ethers.getContractFactory("RuneToken");
        return await RuneToken.deploy(
            tokenName,
            tokenSymbol,
            rune,
            runeDivisibility,
        );
    }

    async function testTokenFixture() {
        return await deploy({
            tokenName: "SOMERUNE",
            tokenSymbol: "R",
            rune: 12345,
            runeDivisibility: 18,
        });
    }

    it("deploys", async function () {
        const testToken = await loadFixture(testTokenFixture);
        expect(await testToken.name()).to.equal("SOMERUNE");
        expect(await testToken.symbol()).to.equal("R");
        expect(await testToken.totalSupply()).to.equal(0);
        expect(await testToken.decimals()).to.equal(18);
        expect(await testToken.rune()).to.equal(12345);
    });
});
