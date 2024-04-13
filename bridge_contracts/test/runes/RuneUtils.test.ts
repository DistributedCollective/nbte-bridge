import {
  loadFixture,
} from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from "chai";
import { ethers } from "hardhat";

describe("RuneUtils", function () {
  async function deployRuneUtilsFixture() {
    const RuneUtils = await ethers.getContractFactory("RuneUtils");
    const runeUtils = await RuneUtils.deploy();

    return { runeUtils };
  }

  it("runeNumberToName", async function () {
    const {runeUtils} = await loadFixture(deployRuneUtilsFixture);
    expect(await runeUtils.runeNumberToName(2n ** 128n - 1n)).to.equal('BCGDENLQRQWDSLRUGSNLBTMFIJAV');
    expect(await runeUtils.runeNumberToName(1378097814235)).to.equal('FOOBARBAZ');
    expect(await runeUtils.runeNumberToName(1)).to.equal('B');
    expect(await runeUtils.runeNumberToName(0)).to.equal('A');
  });

  it("runeNameToNumber", async function () {
    const {runeUtils} = await loadFixture(deployRuneUtilsFixture);
    expect(await runeUtils.runeNameToNumber('BCGDENLQRQWDSLRUGSNLBTMFIJAV')).to.equal(2n ** 128n - 1n);
    expect(await runeUtils.runeNameToNumber('FOOBARBAZ')).to.equal(1378097814235);
    expect(await runeUtils.runeNameToNumber('B')).to.equal(1);
    expect(await runeUtils.runeNameToNumber('A')).to.equal(0);
  });

  it("spacedRuneToNumberAndSpacers", async function () {
    const {runeUtils} = await loadFixture(deployRuneUtilsFixture);
    let number, spacers;
    [number, spacers] = await runeUtils.spacedRuneToNumberAndSpacers('BCGDENLQRQWDSLRUGSNLBTMFIJAV');
    expect(number).to.equal(2n ** 128n - 1n);
    expect(spacers).to.equal(0);

    [number, spacers] = await runeUtils.spacedRuneToNumberAndSpacers('FOOBARBAZ');
    expect(number).to.equal(1378097814235);
    expect(spacers).to.equal(0);

    [number, spacers] = await runeUtils.spacedRuneToNumberAndSpacers('FOOBAR.BAZ');
    expect(number).to.equal(1378097814235);
    expect(spacers).to.equal(32);

    [number, spacers] = await runeUtils.spacedRuneToNumberAndSpacers('FOOBAR•BAZ');
    expect(number).to.equal(1378097814235);
    expect(spacers).to.equal(32);
  });

  it("numberAndSpacersToSpacedRune", async function () {
    const {runeUtils} = await loadFixture(deployRuneUtilsFixture);
    expect(await runeUtils.numberAndSpacersToSpacedRune(2n ** 128n - 1n, 0)).to.equal('BCGDENLQRQWDSLRUGSNLBTMFIJAV');
    expect(await runeUtils.numberAndSpacersToSpacedRune(1378097814235, 0)).to.equal('FOOBARBAZ');
    expect(await runeUtils.numberAndSpacersToSpacedRune(1378097814235, 32)).to.equal('FOOBAR.BAZ');
    expect(await runeUtils.numberAndSpacersToSpacedRune(0, 0)).to.equal('A');
  });
});
