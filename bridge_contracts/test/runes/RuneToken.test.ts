import {loadFixture} from "@nomicfoundation/hardhat-toolbox/network-helpers";
import {ethers} from "hardhat";
import {expect} from 'chai';


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

    describe('mintTo', function () {
        it('mints tokens', async function () {
            const testToken = await loadFixture(testTokenFixture);
            const user = (await ethers.getSigners())[1];
            const address = await user.getAddress();
            await expect(testToken.mintTo(address, 1000)).to.changeTokenBalance(
                testToken,
                user,
                1000
            );
            expect(await testToken.balanceOf(address)).to.equal(1000);
            expect(await testToken.totalSupply()).to.equal(1000);
        });

        it('reverts if not called by minter', async function () {
            const testToken = await loadFixture(testTokenFixture);
            const anotherUser = (await ethers.getSigners())[1];
            await expect(
                (
                    testToken.connect(
                        anotherUser
                    ) as typeof testToken
                ).mintTo(
                    await anotherUser.getAddress(),
                    1000,
                )
            ).to.be.revertedWith('only callable by minter');
        });
    });

    describe('changeMinter', () => {
        it('is only callable by the minter', async () => {
            const testToken = await loadFixture(testTokenFixture);
            const [_, other] = await ethers.getSigners();
            await expect(
                (testToken.connect(other) as typeof testToken).changeMinter(await other.getAddress())
            ).to.be.revertedWith('only callable by minter');
        });
    });
});
