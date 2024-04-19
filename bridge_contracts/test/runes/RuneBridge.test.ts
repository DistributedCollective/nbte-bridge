import {
    loadFixture,
} from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from 'chai';
import { ethers, upgrades } from "hardhat";
import { Signer } from 'ethers';
import {
    reasonNotAdmin,
    reasonNotGuard,
    reasonNotPauser,
    setRuneTokenBalance,
} from "./utils";
import {RuneToken} from '../../typechain-types';

const ADDRESS_ZERO = "0x0000000000000000000000000000000000000000";
const ADDRESS_RANDOM = "0x0000000000000000000000000000000000000123";

describe("RuneBridge", function () {
    let owner: Signer;
    let federator1: Signer;
    let federator2: Signer;
    let federator3: Signer;
    let user: Signer;
    let user2: Signer;
    let federators: Signer[];

    beforeEach(async function () {
        [owner, federator1, federator2, federator3, user, user2] = await ethers.getSigners();
        federators = [federator1, federator2, federator3];
    });

    async function runeBridgeFixture() {
        const NBTEBridgeAccessControl = await ethers.getContractFactory("NBTEBridgeAccessControl");
        const accessControl = await NBTEBridgeAccessControl.deploy();
        for(const federator of federators) {
            await accessControl.addFederator(await federator.getAddress());
        }

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

        // disable policy for easier testing
        await runeBridge.setEvmToBtcTransferPolicy(
            ADDRESS_ZERO,
            ethers.parseEther("1000000000"),
            0,
            0,
            0,
            0,
        )

        const RuneToken = await ethers.getContractFactory("RuneToken");

        const rune = 162415998996;
        await runeBridge.registerRune(
            "TEST•RUNE",
            "R",
            rune,
            18,
        );
        const runeTokenAddress = await runeBridge.getTokenByRune(rune);
        const runeToken = RuneToken.attach(runeTokenAddress);

        const userRuneBridge = runeBridge.connect(user) as typeof runeBridge;

        return {
            runeBridge,
            userRuneBridge,
            btcAddressValidator,
            accessControl,
            rune,
            runeToken,
        };
    }

    it("deploys", async function () {
        const { runeBridge } = await loadFixture(runeBridgeFixture);
        expect(await runeBridge.numRunesRegistered()).to.equal(1);
    });

    it('setRuneTokenBalance helper', async function () {
        const { runeToken } = await loadFixture(runeBridgeFixture);

        let totalSupply = await runeToken.totalSupply();
        let bal = await runeToken.balanceOf(await owner.getAddress());
        expect(bal).to.equal(0);

        await setRuneTokenBalance(runeToken, owner, 10);

        bal = await runeToken.balanceOf(await owner.getAddress());
        expect(bal).to.equal(10);

        totalSupply = await runeToken.totalSupply();
        expect(totalSupply).to.equal(10);


        await setRuneTokenBalance(runeToken, user, 20);

        // total supply is affected
        totalSupply = await runeToken.totalSupply();
        expect(totalSupply).to.equal(30);

        // user balance changes
        bal = await runeToken.balanceOf(await user.getAddress());
        expect(bal).to.equal(20);

        // owner balance unchanged
        bal = await runeToken.balanceOf(await owner.getAddress());
        expect(bal).to.equal(10);

        await setRuneTokenBalance(runeToken, owner, 5);
        totalSupply = await runeToken.totalSupply();
        expect(totalSupply).to.equal(25);
        bal = await runeToken.balanceOf(await owner.getAddress());
        expect(bal).to.equal(5);
    });

    describe("transferToBtc", () => {
        const btcAddress = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq";

        it("doesn't accept unregistered runes", async function () {
            const { runeBridge} = await loadFixture(runeBridgeFixture);

            const RuneToken = await ethers.getContractFactory("RuneToken");
            const fakeRuneToken = await RuneToken.deploy("Rune", "RUNE", 1234, 18);
            await fakeRuneToken.mintTo(await owner.getAddress(), 1000);

            await expect(runeBridge.transferToBtc(
                await fakeRuneToken.getAddress(),
                100,
                btcAddress,
            )).to.be.revertedWith("token not registered");
        });


        it("accepts registered runes", async function () {
            const { runeBridge, runeToken , rune } = await loadFixture(runeBridgeFixture);

            await setRuneTokenBalance(runeToken, owner, 1000);
            await runeToken.approve(await runeBridge.getAddress(), 1000);

            let totalSupply = await runeToken.totalSupply();
            await expect(runeBridge.transferToBtc(
                await runeToken.getAddress(),
                100,
                btcAddress,
            )).to.emit(runeBridge, "RuneTransferToBtc").withArgs(
                1,
                await owner.getAddress(),
                await runeToken.getAddress(),
                rune,
                100,
                100, // net amount
                btcAddress,
                0,
                0,
            );
            // it burns the runes
            expect(await runeToken.totalSupply()).to.equal(totalSupply - 100n);

            await expect(runeBridge.transferToBtc(
                await runeToken.getAddress(),
                100,
                btcAddress,
            )).to.changeTokenBalances(
                runeToken,
                [owner, runeBridge],
                [-100, 0]
            );
        });

        // TODO: it handles fees
        // TODO: not callable when paused
    });

    //     function requestRuneRegistration(
    //     function acceptRuneRegistrationRequest(
    //     function getAcceptRuneRegistrationRequestMessageHash(

    //     function acceptTransferFromBtc(
    //     function getAcceptTransferFromBtcMessageHash(

    //     function withdrawBaseCurrency(
    //     function withdrawTokens(

    describe('registerRune', async () => {
        it('registers rune when called by an admin', async () => {
            const { runeBridge } = await loadFixture(runeBridgeFixture);
            let numRunesRegisteredBefore = await runeBridge.numRunesRegistered();
            await expect(runeBridge.registerRune(
                "Foo",
                "Bar",
                1,
                2
            )).to.emit(runeBridge, "RuneRegistered");
            expect(await runeBridge.numRunesRegistered()).to.equal(numRunesRegisteredBefore + 1n);
        });

        it('is only callable by an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.registerRune(
                "Foo",
                "Bar",
                1,
                2
            )).to.be.revertedWith(
                reasonNotAdmin(await user.getAddress())
            );
        });

        it('does not register the same rune twice', async () => {
            const { runeBridge, rune } = await loadFixture(runeBridgeFixture);

            await expect(runeBridge.registerRune(
                "Foo",
                "Bar",
                rune,
                2
            )).to.be.revertedWith("rune already registered");
        });
    });

    describe('setEvmToBtcTransferPolicy', async () => {
        it('is only callable by an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.setEvmToBtcTransferPolicy(
                ADDRESS_ZERO,
                ethers.parseEther("1000000000"),
                0,
                0,
                0,
                0,
            )).to.be.revertedWith(
                reasonNotAdmin(await user.getAddress())
            );
        });

        // TODO: test it sets the policy
    });

    describe("setRuneRegistrationRequestsEnabled", () => {
        it('is only callable by an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.setRuneRegistrationRequestsEnabled(true)).to.be.revertedWith(
                reasonNotAdmin(await user.getAddress())
            );
        });
    });

    describe("setRuneRegistrationFee", () => {
        it('is only callable by an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.setRuneRegistrationFee(ethers.parseEther("1"))).to.be.revertedWith(
                reasonNotAdmin(await user.getAddress())
            );
        });
    });

    describe("setBtcAddressValidator", () => {
        it('is only callable by an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.setBtcAddressValidator(ADDRESS_RANDOM)).to.be.revertedWith(
                reasonNotAdmin(await user.getAddress())
            );
        });
    });

    describe("setAccessControl", () => {
        it('is only callable by an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.setAccessControl(ADDRESS_RANDOM)).to.be.revertedWith(
                reasonNotAdmin(await user.getAddress())
            );
        });
    });

    describe("pause", () => {
        it('is only callable by a pauser or an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.pause()).to.be.revertedWith(
                reasonNotPauser(await user.getAddress())
            );
        });
    })

    describe("freeze", () => {
        it('is only callable by a guard or an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.freeze()).to.be.revertedWith(
                reasonNotGuard(await user.getAddress())
            );
        });
    });

    describe("unpause", () => {
        it('is only callable by a pauser on ar admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.unpause()).to.be.revertedWith(
                reasonNotPauser(await user.getAddress())
            );
        });
    });

    describe("unfreeze", () => {
        it('is only callable by a guard or an admin', async () => {
            const { userRuneBridge } = await loadFixture(runeBridgeFixture);

            await expect(userRuneBridge.unfreeze()).to.be.revertedWith(
                reasonNotGuard(await user.getAddress())
            );
        });
    });

    // TODO: fees can be withdrawn

    // View methods, can be tested later with more detail

    describe("isRuneRegistered", () => {
        it('works', async () => {
            const { runeBridge, rune } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.isRuneRegistered(rune)).to.be.true;
            expect(await runeBridge.isRuneRegistered(1234)).to.be.false;
        });

    });

    describe("isTokenRegistered", () => {
        it('works', async () => {
            const { runeBridge, runeToken } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.isTokenRegistered(await runeToken.getAddress())).to.be.true;
            expect(await runeBridge.isTokenRegistered(ADDRESS_RANDOM)).to.be.false;
        });
    });

    describe("numRunesRegistered", () => {
        it('works', async () => {
            const { runeBridge } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.numRunesRegistered()).to.equal(1);
        });
    });

    describe("getTokenByRune", () => {
        it('works', async () => {
            const { runeBridge, runeToken, rune } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.getTokenByRune(rune)).to.equal(await runeToken.getAddress());
        });

        it('reverts for unregistered runes', async () => {
            const { runeBridge } = await loadFixture(runeBridgeFixture);

            await expect(runeBridge.getTokenByRune(1234)).to.be.revertedWith("rune not registered");
        });
    });

    describe("getRuneByToken", () => {
        it('works', async () => {
            const { runeBridge, runeToken, rune } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.getRuneByToken(await runeToken.getAddress())).to.equal(rune);
        });

        it('reverts for unregistered tokens', async () => {
            const { runeBridge } = await loadFixture(runeBridgeFixture);

            await expect(runeBridge.getRuneByToken(ADDRESS_RANDOM)).to.be.revertedWith("token not registered");
        });
    });

    describe("listTokens", () => {
        it('works', async () => {
            const { runeBridge, runeToken } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.listTokens()).to.deep.equal([await runeToken.getAddress()]);
        });
    });

    describe("paginateTokens", () => {
        it('works', async () => {
            const { runeBridge, runeToken } = await loadFixture(runeBridgeFixture);

            const token1 = await runeToken.getAddress();

            expect(await runeBridge.paginateTokens(0, 1)).to.deep.equal([token1]);
            expect(await runeBridge.paginateTokens(0, 100)).to.deep.equal([token1]);
            expect(await runeBridge.paginateTokens(1, 0)).to.deep.equal([]);

            await runeBridge.registerRune("Foo", "Bar", 1234, 18);
            const token2 = await runeBridge.getTokenByRune(1234);
            await runeBridge.registerRune("Herp", "Derp", 4567, 1);
            const token3 = await runeBridge.getTokenByRune(4567);

            expect(await runeBridge.paginateTokens(0, 1)).to.deep.equal([token1]);
            expect(await runeBridge.paginateTokens(0, 2)).to.deep.equal([token1, token2]);
            expect(await runeBridge.paginateTokens(0, 3)).to.deep.equal([token1, token2, token3]);
            expect(await runeBridge.paginateTokens(1, 1)).to.deep.equal([token2]);
            expect(await runeBridge.paginateTokens(1, 2)).to.deep.equal([token2, token3]);
            expect(await runeBridge.paginateTokens(2, 1)).to.deep.equal([token3]);
        });
    });

    describe("getEvmToBtcTransferPolicy", () => {
        it('returns the default policy for address zero', async () => {
            const { runeBridge } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.getEvmToBtcTransferPolicy(ADDRESS_ZERO)).to.deep.equal([
                ethers.parseEther("1000000000"),
                0,
                0,
                0,
                0,
            ]);
        });

        it('returns the policy set for token', async () => {
            const { runeBridge, runeToken } = await loadFixture(runeBridgeFixture);

            const policy = [
                await runeToken.getAddress(),
                ethers.parseEther("1234567890"),
                1,
                2,
                3,
                4,
            ];
            await runeBridge.setEvmToBtcTransferPolicy(...policy);

            // token is not a part of the stored policy
            expect(await runeBridge.getEvmToBtcTransferPolicy(await runeToken.getAddress())).to.deep.equal(policy.slice(1));
        });

        it('returns the default policy if policy is not set for token', async () => {
            const { runeBridge, runeToken } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.getEvmToBtcTransferPolicy(await runeToken.getAddress())).to.deep.equal([
                ethers.parseEther("1000000000"),
                0,
                0,
                0,
                0,
            ]);
        });

        it('reverts for unregistered tokens', async () => {
            const { runeBridge } = await loadFixture(runeBridgeFixture);

            await expect(runeBridge.getEvmToBtcTransferPolicy(ADDRESS_RANDOM)).to.be.revertedWith("token not registered");
        });
    });

    describe("isTransferFromBtcProcessed", () => {
        it('works', async () => {
            const { runeBridge , rune } = await loadFixture(runeBridgeFixture);

            expect(await runeBridge.isTransferFromBtcProcessed(
                "0x0000000000000000000000000000000000000000000000000000000000000001",
                1,
                rune
            )).to.be.false;
        });
    });

    // These just delegate to other contracts
    //     function isValidBtcAddress(string calldata btcAddress) public view returns (bool) {
    //     function numRequiredFederators() public view returns (uint256) {
    //     function isFederator(address addressToCheck) external view returns (bool) {
});
