import {loadFixture,} from "@nomicfoundation/hardhat-toolbox/network-helpers";
import {expect} from 'chai';
import {ethers, upgrades} from "hardhat";
import {Contract, Signer} from 'ethers';
import {setBalance} from "@nomicfoundation/hardhat-network-helpers";
import {
  bigIntToScientificNotation,
  createHandlesFeesTestCases,
  createHandlesFeesWithFeesTestCases,
  extractFractionalAmount,
  getRuneAmount,
  getTokenAmount,
  reasonNotAdmin,
  reasonNotEnoughSignatures,
  reasonNotFederator,
  reasonNotGuard,
  reasonNotPauser,
  reasonTransferAlreadyProcessed,
  setEvmToBtcTransferPolicy,
  setRuneTokenBalance,
  transferToBtcAndExpectEvent,
} from "./utils";
import {
  defaultRune,
  reasonIncorrectBaseCurrencyFee,
  reasonNetRuneAmountIsZero,
  reasonRegistrationNotRequested,
  reasonRuneAlreadyRegistered,
  reasonTokenAmountLessThanFees,
} from "./constants";

import {EvmToBtcTransferPolicy, TransferToBtcAndExpectEventProps} from "./types";

const ADDRESS_ZERO = "0x0000000000000000000000000000000000000000";
const ADDRESS_RANDOM = "0x0000000000000000000000000000000000000123";

describe("RuneBridge", function () {
  let owner: Signer;
  let federator1: Signer;
  let federator2: Signer;
  let federator3: Signer;
  let user: Signer;
  let federators: Signer[];

  before(async function () {
    [owner, federator1, federator2, federator3, user] = await ethers.getSigners();
    federators = [federator1, federator2, federator3];
  });

  async function runeBridgeFixture() {
    const NBTEBridgeAccessControl = await ethers.getContractFactory("NBTEBridgeAccessControl");
    const accessControl = await NBTEBridgeAccessControl.deploy();
    for (const federator of federators) {
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

    // disable fees for easier testing
    await runeBridge.setEvmToBtcTransferPolicy(
      ADDRESS_ZERO,
      ethers.parseEther("1000000000"),
      0,
      0,
      0,
      0,
    );
    await runeBridge.setRuneRegistrationFee(0);

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
    const userRuneToken = runeToken.connect(user) as typeof runeToken;

    const federatorRuneBridge = runeBridge.connect(federator1) as typeof runeBridge;

    return {
      runeBridge,
      userRuneBridge,
      federatorRuneBridge,
      btcAddressValidator,
      accessControl,
      rune,
      runeToken,
      userRuneToken,
    };
  }

  it("deploys", async function () {
    const {runeBridge} = await loadFixture(runeBridgeFixture);
    expect(await runeBridge.numRunesRegistered()).to.equal(1);
  });

  it('setRuneTokenBalance helper', async function () {
    const {runeToken} = await loadFixture(runeBridgeFixture);

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
      const {runeBridge} = await loadFixture(runeBridgeFixture);

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
      const {runeBridge, runeToken, rune} = await loadFixture(runeBridgeFixture);

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

    it('reverts when paused', async () => {
      const {runeBridge, runeToken} = await loadFixture(runeBridgeFixture);

      await setRuneTokenBalance(runeToken, owner, 1000);
      await runeToken.approve(await runeBridge.getAddress(), 1000);

      await runeBridge.pause();
      await expect(runeBridge.transferToBtc(
        await runeToken.getAddress(),
        100,
        btcAddress,
      )).to.be.revertedWith("Pausable: paused");
    });

    it('is callable by a normal user', async () => {
      const {runeBridge, userRuneToken, userRuneBridge} = await loadFixture(runeBridgeFixture);

      await setRuneTokenBalance(userRuneToken, user, 1000);
      await userRuneToken.approve(await runeBridge.getAddress(), 1000);

      await expect(userRuneBridge.transferToBtc(
        await userRuneToken.getAddress(),
        100,
        btcAddress,
      )).to.emit(runeBridge, "RuneTransferToBtc");
    });

    describe('handles fees', () => {
      // TODO: Need to fix this test, it's not working if we run it only. It's working if we run the TransferToBtc test.
      let runeBridge: Contract;
      let runeToken: Contract;
      let rune: number;
      let defaultPolicy: EvmToBtcTransferPolicy;
      let defaultExpectedParams: TransferToBtcAndExpectEventProps;
      const testData: {
        name: string;
        // the partials will be merged with defaults set in beforeEach
        policy: Partial<EvmToBtcTransferPolicy>,
        expectedParams: Partial<Omit<TransferToBtcAndExpectEventProps, 'args'>> & {args: Partial<TransferToBtcAndExpectEventProps["args"]>},
      }[] = [
        {
          name: 'test flat token fee 1',
          policy: {flatFeeTokens: 20},
          expectedParams: {
            args: {
              netRuneAmount: 80,
              tokenFee: 20
            }
          }
        },
        {
          name: 'test flat token fee 2',
          policy: {flatFeeTokens: 30},
          expectedParams: {
            transferAmount: 120,
            args: {
              transferredTokenAmount: 120,
              netRuneAmount: 90,
              tokenFee: 30,
            }
          },
        },
        {
          name: 'test dynamic token fee',
          policy: {dynamicFeeTokens: 300},
          /// 300 / 10_000
          expectedParams: {
            args: {
              transferredTokenAmount: 100,
              netRuneAmount: 97,
              tokenFee: 3,
            }
          },
        },
        {
          name: 'test flatFeeBaseCurrency',
          policy: {flatFeeBaseCurrency: ethers.parseEther('1')},
          expectedParams: {
            args: {
              baseCurrencyFee: ethers.parseEther('1'),
            }
          },
        },
        // flat fee + dynamic fee (tokens)
        {
          name: 'test flat fee + dynamic fee (tokens)',
          policy: {flatFeeTokens: 15, dynamicFeeTokens: 400},
          expectedParams: {
            transferAmount: 120,
            args: {
              transferredTokenAmount: 120,
              netRuneAmount: 101,
              tokenFee: 19,
            }
          }
        },
        // transfer a tiny amount so that rounding for dynamic fees is required
        // f.ex. transfer 10 (not parseEther('10')!), dynamic fee = 1%
        // Current implementation is to round down the fee.
        {
          name: 'test transfer a tiny amount',
          policy: {dynamicFeeTokens: 100},
          expectedParams: {
            transferAmount: 10,
            args: {
              transferredTokenAmount: 10,
              netRuneAmount: 10,
              tokenFee: 0,
            }
          }
        },
      ]

      beforeEach(async () => {
        ({runeBridge, runeToken, rune} = await loadFixture(runeBridgeFixture));
        const initFund = ethers.parseUnits("1000", 18);
        await setRuneTokenBalance(runeToken, owner, initFund);
        await runeToken.approve(await runeBridge.getAddress(), initFund);
        defaultPolicy = {
          runeBridgeContract: runeBridge,
          tokenAddress: await runeToken.getAddress(),
          maxTokenAmount: ethers.parseEther('1000'),
          minTokenAmount: 1,
          flatFeeBaseCurrency: 0,
          flatFeeTokens: 0,
          dynamicFeeTokens: 0,
        }
        defaultExpectedParams = {
          transferAmount: 100,
          runeBridgeContract: runeBridge,
          tokenAddress: await runeToken.getAddress(),
          btcAddress: btcAddress,
          emit: {contract: runeBridge, eventName: "RuneTransferToBtc"},
          args: {
            counter: 1,
            from: await owner.getAddress(),
            token: await runeToken.getAddress(),
            rune,
            transferredTokenAmount: 100,
            netRuneAmount: 100,
            receiverBtcAddress: btcAddress,
            baseCurrencyFee: 0,
            tokenFee: 0,
          }
        }
      });

      it('trying to transfer less than fees', async () => {
        const policy = {
          ...defaultPolicy,
          flatFeeTokens: 10,
        }
        const transferAmount = 10;
        const baseCurrencyFee = 10;
        await setEvmToBtcTransferPolicy(policy)
        await expect(runeBridge.transferToBtc(
          await runeToken.getAddress(),
          transferAmount,
          btcAddress,
          {value: baseCurrencyFee}
        )).to.be.revertedWith(reasonIncorrectBaseCurrencyFee);
      });

      for (const testCase of testData) {
        it(testCase.name, async () => {
          const policy: EvmToBtcTransferPolicy = {
            ...defaultPolicy,
            ...testCase.policy,
          }
          const expectedParams: TransferToBtcAndExpectEventProps = {
            ...defaultExpectedParams,
            ...testCase.expectedParams,
            args: {
                ...defaultExpectedParams.args,
                ...testCase.expectedParams.args,
            }
          }
          const ownerRuneTokenBalanceBefore = await runeToken.balanceOf(await owner.getAddress());
          const runeBridgeRuneTokenBalanceBefore = await runeToken.balanceOf(await runeBridge.getAddress());
          const runeBridgeBaseCurrencyBalanceBefore = await ethers.provider.getBalance(await runeBridge.getAddress());

          await setEvmToBtcTransferPolicy(policy);
          await transferToBtcAndExpectEvent(expectedParams);

          // User balance change for tokens (should decrease by the full sent amount)
          const ownerRuneTokenBalanceAfter = await runeToken.balanceOf(await owner.getAddress());
          const expectedOwnerRuneBalance = ownerRuneTokenBalanceBefore - ownerRuneTokenBalanceAfter;
          expect(expectedOwnerRuneBalance).to.equal(expectedParams.transferAmount);

          // Contract balance change for tokens (fees) (should increase by fee amount)
          const runeBridgeRuneTokenBalanceAfter = await runeToken.balanceOf(await runeBridge.getAddress());
          const expectedRuneBridgeRuneBalance = runeBridgeRuneTokenBalanceBefore + BigInt(expectedParams.args.tokenFee);
          expect(expectedRuneBridgeRuneBalance).to.equal(runeBridgeRuneTokenBalanceAfter);

          // Contract balance for base currency (should increase by flatFeeBaseCurrency)
          const runeBridgeBaseCurrencyBalanceAfter = await ethers.provider.getBalance(await runeBridge.getAddress());
          const expectedRunBridgeBaseCurrencyBalance = runeBridgeBaseCurrencyBalanceBefore + BigInt(expectedParams.args.baseCurrencyFee);
          expect(expectedRunBridgeBaseCurrencyBalance).to.equal(runeBridgeBaseCurrencyBalanceAfter);

          // TODO: OPTIONAL: test user balance change for base currency (should decrease by flatFeeBaseCurrency + tx cost, tricky to test
        });
      }
    });

    /*
     * tests for these cases
     * Rune Decimals | Token Decimals | Transferred token amount (base units)  | Received rune amount (base units) | Received fees (token base units)
     * 18            | 18             | 100e18                                 | 100e18                            | 0
     * 23            | 23             | 100e23                                 | 100e23                            | 0
     *  8            | 18             | 100e18                                 | 100e8                             | 0
     *  8            | 18             | 1e18                                   | 1e8                               | 0
     *  8            | 18             | 1e10                                   | 1e0 = 1                           | 0
     *  8            | 18             | 1e12                                   | 1e2 = 100                         | 0
     *  8            | 18             | 1e9                                    | 0.1 = ERROR!                      | 0
     *  8            | 18             | 1e7                                    | 0.01 = ERROR!                     | 0
     *  9            | 18             | 1e10                                   | 1e1 = 10                          | 0
     *  6            | 18             | 1e10                                   | 1e-2 = 0.01 = ERROR!              | 0
     *  8            | 18             | 1e10 + 1e9 = 11000000000               | 1.1 = 1 (rest kept as fees)       | 1e9
     * 100e8 = parseUnits(100, 8)
     */
    describe('handles runes with different divisibilities', () => {
      let runeBridge: Contract;
      let runeToken: Contract;
      let counter: number = 1;
      let rune: number = defaultRune;
      beforeEach(async () => {
        ({runeBridge} = await loadFixture(runeBridgeFixture));
      })
      const testCases = createHandlesFeesTestCases();
      testCases.forEach((
        {
          runeDecimals,
          amountToTransferDecimals,
          amountToTransfer,
          expectedTokenFee,
          baseCurrencyFee,
          isError
        }) => {
        const title = [
          `handle transfer case with runeDecimals: ${runeDecimals}`,
          `amountToTransferDecimals: ${amountToTransferDecimals}`,
          `amountToTransfer: ${amountToTransfer.toString()}`,
          `expectedFees: ${bigIntToScientificNotation(BigInt(expectedTokenFee))}`
        ].join(', ');
        it(title, async () => {
          const RuneToken = await ethers.getContractFactory("RuneToken");
          await runeBridge.registerRune(
            "TEST•LOHI",
            "LH",
            rune,
            runeDecimals,
          );
          const runeTokenAddress = await runeBridge.getTokenByRune(rune);
          runeToken = RuneToken.attach(runeTokenAddress);

          const amount = ethers.parseUnits("20000", runeDecimals < 18 ? 18 : runeDecimals);
          await setRuneTokenBalance(runeToken, owner, amount);
          await runeToken.approve(await runeBridge.getAddress(), amount);
          const transferredTokenAmount = ethers.parseUnits(String(amountToTransfer), amountToTransferDecimals);
          const tokenDecimals = await runeToken.decimals();
          const netRuneAmount = getRuneAmount(Number(runeDecimals), Number(tokenDecimals), transferredTokenAmount);

          if (isError) {
            return expect(runeBridge.transferToBtc(
              await runeToken.getAddress(),
              transferredTokenAmount,
              btcAddress,
            )).to.be.revertedWith(reasonNetRuneAmountIsZero);
          }

          await expect(runeBridge.transferToBtc(
            await runeToken.getAddress(),
            transferredTokenAmount,
            btcAddress,
          )).to.emit(runeBridge, "RuneTransferToBtc").withArgs(
            counter,
            await owner.getAddress(),
            await runeToken.getAddress(),
            rune,
            transferredTokenAmount,
            netRuneAmount, // net amount
            btcAddress,
            baseCurrencyFee,
            expectedTokenFee,
          );
        });
      });
    });

    describe('handles runes with different divisibilities and fees', () => {
      let runeBridge: Contract;
      let runeToken: Contract;
      let counter: number = 1;
      let rune: number = defaultRune;
      beforeEach(async () => {
        ({runeBridge} = await loadFixture(runeBridgeFixture));
      })
      const testCasesWithFees = createHandlesFeesWithFeesTestCases();
      testCasesWithFees.forEach(
        ({
           title,
           policy,
           runeDecimals,
           amountToTransferDecimals,
           amountToTransfer,
           baseCurrencyFee,
           isError
         }) => {
          it(title, async () => {
            const RuneToken = await ethers.getContractFactory("RuneToken");
            await runeBridge.registerRune(
              "TEST•LOHI",
              "LH",
              rune,
              runeDecimals,
            );
            const runeTokenAddress = await runeBridge.getTokenByRune(rune);
            runeToken = RuneToken.attach(runeTokenAddress);

            const amount = ethers.parseUnits("1000", runeDecimals < 18 ? 18 : runeDecimals);
            await setRuneTokenBalance(runeToken, owner, amount);
            await runeToken.approve(await runeBridge.getAddress(), amount);
            const tokenDecimals = await runeToken.decimals();

            const transferredTokenAmount = ethers.parseUnits(String(amountToTransfer), amountToTransferDecimals);
            const {fractionalAmountAsTokenFee} = extractFractionalAmount(transferredTokenAmount, runeDecimals, tokenDecimals);
            const flatTokenFee = getTokenAmount(Number(runeDecimals), Number(tokenDecimals), BigInt(policy.flatFeeTokens));
            const dynamicFeeTokenDivisor = getTokenAmount(Number(runeDecimals), Number(tokenDecimals), BigInt(10_000));
            const dynamicFeeToken = getTokenAmount(Number(runeDecimals), Number(tokenDecimals), BigInt(policy.dynamicFeeTokens));
            const tokenFees = flatTokenFee + ((transferredTokenAmount * dynamicFeeToken) / dynamicFeeTokenDivisor) + fractionalAmountAsTokenFee;

            const newPolicy: EvmToBtcTransferPolicy = {
              ...policy,
              runeBridgeContract: runeBridge,
              tokenAddress: await runeToken.getAddress(),
              flatFeeTokens: runeDecimals < 18 ? flatTokenFee : policy.flatFeeTokens,
            };
            await setEvmToBtcTransferPolicy(newPolicy);

            const netRuneAmountBeforeAdjustment = transferredTokenAmount - tokenFees;
            const netRuneAmount = getRuneAmount(Number(runeDecimals), Number(tokenDecimals), netRuneAmountBeforeAdjustment);
            const expectedTokenFee = transferredTokenAmount - getTokenAmount(runeDecimals, tokenDecimals, netRuneAmount);

            if (netRuneAmount === 0n) {
              return expect(runeBridge.transferToBtc(
                await runeToken.getAddress(),
                transferredTokenAmount,
                btcAddress,
              )).to.be.revertedWith(reasonNetRuneAmountIsZero);
            } else if (transferredTokenAmount < expectedTokenFee) {
              return expect(runeBridge.transferToBtc(
                await runeToken.getAddress(),
                transferredTokenAmount,
                btcAddress,
              )).to.be.revertedWith(reasonTokenAmountLessThanFees);
            }
            await expect(runeBridge.transferToBtc(
              await runeToken.getAddress(),
              transferredTokenAmount,
              btcAddress,
            )).to.emit(runeBridge, "RuneTransferToBtc").withArgs(
              counter,
              await owner.getAddress(),
              await runeToken.getAddress(),
              rune,
              transferredTokenAmount,
              netRuneAmount, // net amount
              btcAddress,
              baseCurrencyFee,
              expectedTokenFee,
            );
          });

        });
    });
  });


  describe("requestRuneRegistration", () => {
    it("works", async function () {
      const {runeBridge, userRuneBridge} = await loadFixture(runeBridgeFixture);

      await runeBridge.setRuneRegistrationRequestsEnabled(true);
      await expect(userRuneBridge.requestRuneRegistration(
        1234,
      )).to.emit(runeBridge, "RuneRegistrationRequested").withArgs(
        1234,
        await user.getAddress(),
        0,
      );
    });

    it("reverts for already registered runes", async function () {
      const {runeBridge, userRuneBridge, rune} = await loadFixture(runeBridgeFixture);

      await runeBridge.setRuneRegistrationRequestsEnabled(true);
      await expect(userRuneBridge.requestRuneRegistration(
        rune,
      )).to.be.revertedWith("rune already registered");
    });

    it('reverts if registration is already requested', async () => {
      const {runeBridge, userRuneBridge} = await loadFixture(runeBridgeFixture);

      await runeBridge.setRuneRegistrationRequestsEnabled(true);
      await userRuneBridge.requestRuneRegistration(1234);
      await expect(userRuneBridge.requestRuneRegistration(1234)).to.be.revertedWith("registration already requested");
    });

    it('reverts if registration is disabled', async () => {
      const {runeBridge, userRuneBridge} = await loadFixture(runeBridgeFixture);

      await runeBridge.setRuneRegistrationRequestsEnabled(false);
      await expect(userRuneBridge.requestRuneRegistration(1234)).to.be.revertedWith("rune registration requests disabled");
    });

    it('reverts by default because registration requests are disabled', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.requestRuneRegistration(1234)).to.be.revertedWith("rune registration requests disabled");
    });

    it('reverts for invalid rune numbers', async () => {
      const {runeBridge, userRuneBridge} = await loadFixture(runeBridgeFixture);

      await runeBridge.setRuneRegistrationRequestsEnabled(true);
      await expect(userRuneBridge.requestRuneRegistration(0)).to.be.revertedWith("rune cannot be zero");
      await expect(userRuneBridge.requestRuneRegistration(2n ** 128n)).to.be.revertedWith("rune too large");
    });
  });

  describe("acceptTransferFromBtc", () => {
    let btcTxId: string,
      btcTxVout: number,
      runeAmount: number,
      data: any[],
      hash,
      hashBytes: Uint8Array,
      federatorSignatures: string[],
      runeBridge: Contract,
      rune: number,
      federatorRuneBridge: Contract,
      numTransfersTotal: number = 1
    ;
    beforeEach(async () => {
      ({runeBridge, rune, federatorRuneBridge} = await loadFixture(runeBridgeFixture));
      runeAmount = 100
      btcTxId = "0x" + "0".repeat(64);
      btcTxVout = 0;
      data = [
        await user.getAddress(),
        rune,
        runeAmount,
        btcTxId,
        btcTxVout,
      ]
      hash = await federatorRuneBridge.getAcceptTransferFromBtcMessageHash(
        ...data
      );
      hashBytes = ethers.getBytes(hash);
      federatorSignatures = await Promise.all([
        federator1.signMessage(hashBytes),
        federator2.signMessage(hashBytes),
        federator3.signMessage(hashBytes),
      ])
    });

    it('only callable by a federator', async () => {
      await expect(runeBridge.acceptTransferFromBtc(
        await user.getAddress(),
        rune,
        100,
        btcTxId,
        btcTxVout,
        []
      )).to.be.revertedWith(reasonNotFederator(await owner.getAddress()));
    });

    it('test it actually accepts the transfer', async () => {
      const to = await user.getAddress();
      const tokenAddress = await runeBridge.getTokenByRune(rune);
      await expect(federatorRuneBridge.acceptTransferFromBtc(
        ...data,
        federatorSignatures
      )).to.emit(federatorRuneBridge, "RuneTransferFromBtc").withArgs(
        numTransfersTotal,
        to,
        tokenAddress,
        rune,
        runeAmount,
        btcTxId,
        btcTxVout
      );
    });

    it('test it checks that it is not processed', async () => {
      await federatorRuneBridge.acceptTransferFromBtc(
        ...data,
        federatorSignatures
      )
      await expect(federatorRuneBridge.acceptTransferFromBtc(
        ...data,
        federatorSignatures
      )).to.be.revertedWith(
        reasonTransferAlreadyProcessed()
      )
    });

    it('test it checks signatures', async () => {
      // No signatures
      await expect(federatorRuneBridge.acceptTransferFromBtc(
        ...data,
        []
      )).to.be.revertedWith(reasonNotEnoughSignatures())

      // At least 2 signatures.
      await expect(federatorRuneBridge.acceptTransferFromBtc(
        ...data,
        [await federator2.signMessage(hashBytes)]
      )).to.be.revertedWith(reasonNotEnoughSignatures())

      // Must be federators' signatures
      await expect(federatorRuneBridge.acceptTransferFromBtc(
        ...data,
        [
          await federator2.signMessage(hashBytes),
          await owner.signMessage(hashBytes)
        ]
      )).to.be.revertedWith(reasonNotFederator(await owner.getAddress()))
    });
  });

  describe("acceptRuneRegistrationRequest", () => {
    let federatorRuneBridge: Contract,
      runeBridgeAsAdmin: Contract,
      runeBridgeAsFederator: Contract;
    let name: string,
      symbol: string,
      rune: number,
      runeDivisibility: number,
      data: (string | number)[],
      federatorSignatures: string[];

    beforeEach(async () => {
      ({federatorRuneBridge} = await loadFixture(runeBridgeFixture));
      name = "TEST•VICHY";
      symbol = "RV";
      rune = 162415998100;
      runeDivisibility = 18;
      data = [name, symbol, rune, runeDivisibility]

      runeBridgeAsAdmin = federatorRuneBridge.connect(owner) as typeof federatorRuneBridge;
      await runeBridgeAsAdmin.setRuneRegistrationRequestsEnabled(true);
      runeBridgeAsFederator = runeBridgeAsAdmin.connect(federator1) as typeof federatorRuneBridge;
      await federatorRuneBridge.requestRuneRegistration(rune);
      const hash = await runeBridgeAsFederator.getAcceptRuneRegistrationRequestMessageHash(
        ...data
      );
      const hashBytes = ethers.getBytes(hash);
      federatorSignatures = await Promise.all([
        federator1.signMessage(hashBytes),
        federator2.signMessage(hashBytes),
        federator3.signMessage(hashBytes),
      ])
    })
    it('only callable by a federator', async () => {
      const {runeBridge, runeToken, rune} = await loadFixture(runeBridgeFixture);
      await expect(runeBridge.acceptRuneRegistrationRequest(
        await runeToken.name(),
        await runeToken.symbol(),
        rune,
        await runeToken.decimals(),
        []
      )).to.be.revertedWith(
        reasonNotFederator(await owner.getAddress())
      );
    })
    it('test it only callable if registration requested', async () => {
      await expect(federatorRuneBridge.acceptRuneRegistrationRequest(
        "TEST•VICHY2",
        "RV2",
        162415998101,
        18,
        []
      )).to.be.revertedWith(reasonRegistrationNotRequested)
    })
    it('test it actually accepts the request', async () => {
      await expect(runeBridgeAsFederator.acceptRuneRegistrationRequest(
        ...data,
        federatorSignatures
      )).to.emit(runeBridgeAsFederator, "RuneRegistered");
      const RuneToken = await ethers.getContractFactory("RuneToken");
      const token = RuneToken.attach(await runeBridgeAsFederator.getTokenByRune(rune));
      expect(await token.name()).to.equal(name);
      expect(await token.symbol()).to.equal(symbol);
      expect(await token.rune()).to.equal(rune);
      expect(await token.decimals()).to.equal(runeDivisibility);
    })
    it('test rune is not already registered', async () => {

      await expect(runeBridgeAsFederator.acceptRuneRegistrationRequest(
        ...data,
        federatorSignatures
      )).to.be.emit(runeBridgeAsFederator, "RuneRegistered");

      await expect(runeBridgeAsFederator.acceptRuneRegistrationRequest(
        ...data,
        federatorSignatures
      )).to.be.revertedWith(reasonRuneAlreadyRegistered)
    })
    it('test it checks signatures', async () => {
      const hash = await runeBridgeAsFederator.getAcceptRuneRegistrationRequestMessageHash(
        ...data
      );
      const hashBytes = ethers.getBytes(hash);

      await expect(runeBridgeAsFederator.acceptRuneRegistrationRequest(
        ...data,
        [federator1.signMessage(hashBytes)]
      )).to.be.revertedWith(reasonNotEnoughSignatures())

      await expect(runeBridgeAsFederator.acceptRuneRegistrationRequest(
        ...data,
        []
      )).to.be.revertedWith(reasonNotEnoughSignatures())

      await expect(runeBridgeAsFederator.acceptRuneRegistrationRequest(
        ...data,
        [federator1.signMessage(hashBytes), owner.signMessage(hashBytes)]
      )).to.be.revertedWith(reasonNotFederator(await owner.getAddress()))
    })
  });

  describe("withdrawBaseCurrency", () => {
    it('is only callable by an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await setBalance(await userRuneBridge.getAddress(), 100);
      await expect(userRuneBridge.withdrawBaseCurrency(100, await user.getAddress())).to.be.revertedWith(
        reasonNotAdmin(await user.getAddress())
      );
    });

    it('sent base currency fees can be withdrawn', async () => {
      const {runeBridge, userRuneBridge, userRuneToken} = await loadFixture(runeBridgeFixture);

      await setBalance(await runeBridge.getAddress(), 200);
      await expect(runeBridge.withdrawBaseCurrency(200, await owner.getAddress())).to.changeEtherBalance(
        owner,
        200
      );
    });
  });

  describe("withdrawTokens", () => {
    it('is only callable by an admin', async () => {
      const {userRuneToken, userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.withdrawTokens(
        await userRuneToken.getAddress(),
        100,
        await userRuneBridge.getAddress()
      )).to.be.revertedWith(
        reasonNotAdmin(await user.getAddress())
      );
    });

    it('sent tokens can be withdrawn', async () => {
      const {runeBridge, userRuneBridge, userRuneToken} = await loadFixture(runeBridgeFixture);

      await setRuneTokenBalance(userRuneToken, user, 100);
      await userRuneToken.transfer(await runeBridge.getAddress(), 100);

      await expect(runeBridge.withdrawTokens(
        await userRuneToken.getAddress(),
        100,
        await owner.getAddress()
      )).to.changeTokenBalances(
        userRuneToken,
        [runeBridge, owner],
        [-100, 100]
      );
    });
  });

  describe('registerRune', async () => {
    it('registers rune when called by an admin', async () => {
      const {runeBridge} = await loadFixture(runeBridgeFixture);
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
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

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
      const {runeBridge, rune} = await loadFixture(runeBridgeFixture);

      await expect(runeBridge.registerRune(
        "Foo",
        "Bar",
        rune,
        2
      )).to.be.revertedWith("rune already registered");
    });

    it('deploys tokens', async () => {
      const {runeBridge} = await loadFixture(runeBridgeFixture);

      const RuneToken = await ethers.getContractFactory("RuneToken");


      await runeBridge.registerRune(
        "Foo",
        "Bar",
        123,
        17
      );
      let token = RuneToken.attach(await runeBridge.getTokenByRune(123));
      expect(await token.name()).to.equal("Foo");
      expect(await token.symbol()).to.equal("Bar");
      expect(await token.rune()).to.equal(123);
      expect(await token.decimals()).to.equal(18); // at least 18
    });
  });

  describe('setEvmToBtcTransferPolicy', async () => {
    it('is only callable by an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

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

    it('test it sets the policy', async () => {
      const {runeBridge} = await loadFixture(runeBridgeFixture);
      const policy: EvmToBtcTransferPolicy = {
        runeBridgeContract: runeBridge,
        tokenAddress: ADDRESS_ZERO,
        maxTokenAmount: ethers.parseEther('1000000000'),
        minTokenAmount: 0,
        flatFeeBaseCurrency: 0,
        flatFeeTokens: 0,
        dynamicFeeTokens: 0,
      }
      await expect(runeBridge.setEvmToBtcTransferPolicy(
        policy.tokenAddress,
        policy.maxTokenAmount,
        policy.minTokenAmount,
        policy.flatFeeBaseCurrency,
        policy.flatFeeTokens,
        policy.dynamicFeeTokens,
      )).to.emit(runeBridge, "EvmToBtcTransferPolicyChanged").withArgs(
        policy.tokenAddress,
        policy.maxTokenAmount,
        policy.minTokenAmount,
        policy.flatFeeBaseCurrency,
        policy.flatFeeTokens,
        policy.dynamicFeeTokens,
      );

      const fetchedPolicy = await runeBridge.getEvmToBtcTransferPolicy(policy.tokenAddress);
      const expectedPolicyArray = [
        policy.maxTokenAmount,
        policy.minTokenAmount,
        policy.flatFeeBaseCurrency,
        policy.flatFeeTokens,
        policy.dynamicFeeTokens,
      ];

      expect(fetchedPolicy).to.deep.equal(expectedPolicyArray);
    });
  });

  describe("setRuneRegistrationRequestsEnabled", () => {
    it('is only callable by an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.setRuneRegistrationRequestsEnabled(true)).to.be.revertedWith(
        reasonNotAdmin(await user.getAddress())
      );
    });
  });

  describe("setRuneRegistrationFee", () => {
    it('is only callable by an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.setRuneRegistrationFee(ethers.parseEther("1"))).to.be.revertedWith(
        reasonNotAdmin(await user.getAddress())
      );
    });
  });

  describe("setBtcAddressValidator", () => {
    it('is only callable by an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.setBtcAddressValidator(ADDRESS_RANDOM)).to.be.revertedWith(
        reasonNotAdmin(await user.getAddress())
      );
    });
  });

  describe("setAccessControl", () => {
    it('is only callable by an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.setAccessControl(ADDRESS_RANDOM)).to.be.revertedWith(
        reasonNotAdmin(await user.getAddress())
      );
    });
  });

  describe("pause", () => {
    it('is only callable by a pauser or an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.pause()).to.be.revertedWith(
        reasonNotPauser(await user.getAddress())
      );
    });
  })

  describe("freeze", () => {
    it('is only callable by a guard or an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.freeze()).to.be.revertedWith(
        reasonNotGuard(await user.getAddress())
      );
    });
  });

  describe("unpause", () => {
    it('is only callable by a pauser on ar admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.unpause()).to.be.revertedWith(
        reasonNotPauser(await user.getAddress())
      );
    });
  });

  describe("unfreeze", () => {
    it('is only callable by a guard or an admin', async () => {
      const {userRuneBridge} = await loadFixture(runeBridgeFixture);

      await expect(userRuneBridge.unfreeze()).to.be.revertedWith(
        reasonNotGuard(await user.getAddress())
      );
    });
  });

  // View methods, can be tested later with more detail

  describe("isRuneRegistered", () => {
    it('works', async () => {
      const {runeBridge, rune} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.isRuneRegistered(rune)).to.be.true;
      expect(await runeBridge.isRuneRegistered(1234)).to.be.false;
    });

  });

  describe("isTokenRegistered", () => {
    it('works', async () => {
      const {runeBridge, runeToken} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.isTokenRegistered(await runeToken.getAddress())).to.be.true;
      expect(await runeBridge.isTokenRegistered(ADDRESS_RANDOM)).to.be.false;
    });
  });

  describe("numRunesRegistered", () => {
    it('works', async () => {
      const {runeBridge} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.numRunesRegistered()).to.equal(1);
    });
  });

  describe("getTokenByRune", () => {
    it('works', async () => {
      const {runeBridge, runeToken, rune} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.getTokenByRune(rune)).to.equal(await runeToken.getAddress());
    });

    it('reverts for unregistered runes', async () => {
      const {runeBridge} = await loadFixture(runeBridgeFixture);

      await expect(runeBridge.getTokenByRune(1234)).to.be.revertedWith("rune not registered");
    });
  });

  describe("getRuneByToken", () => {
    it('works', async () => {
      const {runeBridge, runeToken, rune} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.getRuneByToken(await runeToken.getAddress())).to.equal(rune);
    });

    it('reverts for unregistered tokens', async () => {
      const {runeBridge} = await loadFixture(runeBridgeFixture);

      await expect(runeBridge.getRuneByToken(ADDRESS_RANDOM)).to.be.revertedWith("token not registered");
    });
  });

  describe("listTokens", () => {
    it('works', async () => {
      const {runeBridge, runeToken} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.listTokens()).to.deep.equal([await runeToken.getAddress()]);
    });
  });

  describe("paginateTokens", () => {
    it('works', async () => {
      const {runeBridge, runeToken} = await loadFixture(runeBridgeFixture);

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
      const {runeBridge} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.getEvmToBtcTransferPolicy(ADDRESS_ZERO)).to.deep.equal([
        ethers.parseEther("1000000000"),
        0,
        0,
        0,
        0,
      ]);
    });

    it('returns the policy set for token', async () => {
      const {runeBridge, runeToken} = await loadFixture(runeBridgeFixture);

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
      const {runeBridge, runeToken} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.getEvmToBtcTransferPolicy(await runeToken.getAddress())).to.deep.equal([
        ethers.parseEther("1000000000"),
        0,
        0,
        0,
        0,
      ]);
    });

    it('reverts for unregistered tokens', async () => {
      const {runeBridge} = await loadFixture(runeBridgeFixture);

      await expect(runeBridge.getEvmToBtcTransferPolicy(ADDRESS_RANDOM)).to.be.revertedWith("token not registered");
    });
  });

  describe("isTransferFromBtcProcessed", () => {
    it('works', async () => {
      const {runeBridge, rune} = await loadFixture(runeBridgeFixture);

      expect(await runeBridge.isTransferFromBtcProcessed(
        "0x0000000000000000000000000000000000000000000000000000000000000001",
        1,
        rune
      )).to.be.false;
    });
  });

  //     function getAcceptRuneRegistrationRequestMessageHash(
  //     function getAcceptTransferFromBtcMessageHash(

  // These just delegate to other contracts
  //     function isValidBtcAddress(string calldata btcAddress) public view returns (bool) {
  //     function numRequiredFederators() public view returns (uint256) {
  //     function isFederator(address addressToCheck) external view returns (bool) {
});
