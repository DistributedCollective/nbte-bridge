import {getStorageAt, setStorageAt} from "@nomicfoundation/hardhat-network-helpers";
import {ethers} from 'hardhat';
import {BigNumberish, Contract, Signer} from 'ethers';
import {expect} from "chai";
import {
  EvmToBtcTransferPolicy,
  extractFractionalAmountProps,
  HandlesRuneTestCaseProps,
  HandlesRuneWithFeeTestCaseProps,
  TransferToBtcAndExpectEventProps
} from "./types";
import {
  handlesRuneWithDiffDecimalsAndDynamicFeeTokens,
  handlesRuneWithDiffDecimalsAndflatFeeTokens,
  handlesRuneWithDiffDecimalsAndFlatFeeTokensAndDynamicFeeTokens,
  handlesRuneWithDiffDecimalsWithSmallAmountAndDynamicFeeTokens,
  xFail
} from "./constants";

const RUNE_TOKEN_BALANCE_MAPPING_SLOT = 0;
const RUNE_TOKEN_TOTAL_SUPPLY_SLOT = 2;

export async function setRuneTokenBalance(
  runeToken: Contract | string,
  user: Signer | Contract | string,
  balance: BigNumberish
) {
  const runeTokenAddress = typeof runeToken === 'string' ? runeToken : await runeToken.getAddress();
  const userAddress = typeof user === 'string' ? user : await user.getAddress();

  const balanceSlot = ethers.solidityPackedKeccak256(
    ["uint256", "uint256"],
    [userAddress, RUNE_TOKEN_BALANCE_MAPPING_SLOT]
  );

  const balanceBefore = BigInt(
    await getStorageAt(
      runeTokenAddress,
      balanceSlot,
    )
  );
  const totalSupplyBefore = BigInt(
    await getStorageAt(
      runeTokenAddress,
      RUNE_TOKEN_TOTAL_SUPPLY_SLOT,
    )
  );

  const balanceDiff = BigInt(balance) - balanceBefore;

  await setStorageAt(
    runeTokenAddress,
    balanceSlot,
    balance
  );
  await setStorageAt(
    runeTokenAddress,
    RUNE_TOKEN_TOTAL_SUPPLY_SLOT,
    totalSupplyBefore + balanceDiff,
  );
}

export function reasonNotRole(address: string, role: string): string {
  return `AccessControl: account ${address.toLowerCase()} is missing role ${role}`;
}

export function reasonNotAdmin(address: string): string {
  return reasonNotRole(address, "0x0000000000000000000000000000000000000000000000000000000000000000");
}

export function reasonNotPauser(address: string): string {
  return reasonNotRole(address, "0x539440820030c4994db4e31b6b800deafd503688728f932addfe7a410515c14c");
}

export function reasonNotGuard(address: string): string {
  return reasonNotRole(address, "0x25bca7788d8c23352e368ccd4774eb5b5fc3d40422de2c14e98631ab71f33415");
}

export function reasonNotFederator(address: string): string {
  return reasonNotRole(address, "0xd60d8c24d353e0fb03320bff8dd86901186b3566397d831f2dff247991b53f18");
}

export function reasonTransferAlreadyProcessed(): string {
  return "transfer already processed"
}

export function reasonNotEnoughSignatures(): string {
  return 'Not enough signatures'
}

/**
 * Sets the EVM to BTC transfer policy for the Rune Bridge contract.
 *
 * @param {EvmToBtcTransferPolicy} params - The parameters for setting the transfer policy.
 * @param {Contract} params.runeBridgeContract - The Rune Bridge contract instance.
 * @param {string} params.tokenAddress - The address of the token.
 * @param {BigNumberish} params.dynamicFeeTokens - The dynamic fee amount in tokens.
 * @param {BigNumberish} params.flatFeeTokens - The flat fee amount in tokens.
 * @param {BigNumberish} params.minTokenAmount - The minimum amount of tokens for a transfer.
 * @param {BigNumberish} params.maxTokenAmount - The maximum amount of tokens for a transfer.
 * @param {BigNumberish} params.flatFeeBaseCurrency - The flat fee amount in base currency.
 * @returns {Promise<Contract>} A promise that resolves with the updated policy.
 *
 * @example
 * const policyParams = {
 *   runeBridgeContract: someContractInstance,
 *   tokenAddress: '0x123...',
 *   dynamicFeeTokens: 5,
 *   flatFeeTokens: 2,
 *   minTokenAmount: 1,
 *   maxTokenAmount: ethers.utils.parseEther('1000'),
 *   flatFeeBaseCurrency: 0
 * };
 *
 * await setEvmToBtcTransferPolicy(policyParams);
 */
export const setEvmToBtcTransferPolicy = async (
  {
    runeBridgeContract,
    tokenAddress,
    dynamicFeeTokens,
    flatFeeTokens,
    minTokenAmount,
    maxTokenAmount,
    flatFeeBaseCurrency,
  }: EvmToBtcTransferPolicy): Promise<Contract> => {
  if (!runeBridgeContract || !tokenAddress) {
    throw new Error("Rune Bridge contract instance is required.");
  }
  return await runeBridgeContract.setEvmToBtcTransferPolicy(
    tokenAddress,
    maxTokenAmount,
    minTokenAmount,
    flatFeeBaseCurrency,
    flatFeeTokens,
    dynamicFeeTokens,
  );
}


/**
 * Asserts that a function emits an event with specific arguments.
 *
 * @param {TransferToBtcAndExpectEventProps} params - The parameters for the function.
 * @param {Contract} params.runeBridgeContract - The Rune Bridge contract instance.
 * @param {string} params.tokenAddress - The token address.
 * @param {string} params.btcAddress - The BTC address of the receiver.
 * @param {BigNumberish} params.transferAmount - The amount of tokens to be transferred.
 *
 * @param {Object} params.emit - The emit configuration.
 * @param {Contract} emit.contract - The contract that will emit the event.
 * @param {string} emit.eventName - The name of the event to be emitted.
 *
 * @param {Object} params.args - The arguments for the event.
 * @param {number} args.counter - A 1-based counter shared between both types of transfer.
 * @param {string} args.from - The user address.
 * @param {string} args.token - The token address.
 * @param {BigNumberish} args.rune - The base26-encoded rune.
 * @param {BigNumberish} args.transferredTokenAmount - The total amount of tokens sent by the user.
 * @param {BigNumberish} args.netRuneAmount - The amount of runes the receiver will receive.
 * @param {string} args.receiverBtcAddress - The BTC address of the receiver.
 * @param {BigNumberish} args.baseCurrencyFee - The amount of base currency paid as fees.
 * @param {BigNumberish} args.tokenFee - The amount of tokens kept as fees.
 * @returns {Promise<any>} A promise that resolves when the assertion is complete.
 *
 * @example
 * const params = {
 *   runeBridgeContract: someContractInstance,
 *   tokenAddress: '0x456...',
 *   btcAddress: 'someBtcAddress',
 *   transferAmount: 1000,
 *   emit: {
 *     contract: someContractInstance,
 *     eventName: 'RuneTransferToBtc'
 *   },
 *   args: {
 *     counter: 1,
 *     from: '0x123...',
 *     token: '0x456...',
 *     rune: 789,
 *     transferredTokenAmount: 1000,
 *     netRuneAmount: 950,
 *     receiverBtcAddress: 'someBtcAddress',
 *     baseCurrencyFee: 10,
 *     tokenFee: 5,
 *   }
 * };
 *
 * await expectedEmitWithArgs(params);
 */
export const transferToBtcAndExpectEvent = async (
  {
    runeBridgeContract,
    tokenAddress,
    btcAddress,
    transferAmount,
    emit,
    args,
  }: TransferToBtcAndExpectEventProps): Promise<any> => {
  if (!runeBridgeContract || !tokenAddress) {
    throw new Error("Rune Bridge contract instance is required.");
  }
  return expect(
    runeBridgeContract.transferToBtc(
      tokenAddress,
      transferAmount,
      btcAddress,
      {value: args.baseCurrencyFee},
    )
  ).to.emit(
    emit.contract,
    emit.eventName
  ).withArgs(
    args.counter,
    args.from,
    args.token,
    args.rune,
    args.transferredTokenAmount,
    args.netRuneAmount,
    args.receiverBtcAddress,
    args.baseCurrencyFee,
    args.tokenFee
  );
}

export const getSignatures = async (federators: Signer[], runeBridge: Contract, tokenData: any[]) => {
  const hash = await runeBridge.getAcceptRuneRegistrationRequestMessageHash(
    ...tokenData
  );
  const hashBytes = ethers.getBytes(hash);
  return await Promise.all(federators.map(federator => {
    return federator.signMessage(hashBytes)
  }));
}
const calculateDivisor = (runeDecimals: number, tokenDecimals: number): bigint => {
  if (tokenDecimals < runeDecimals) {
    throw new Error("Token decimals should be greater than or equal to rune decimals.");
  }
  const decimalDifference = Number(tokenDecimals) - Number(runeDecimals);
  return BigInt(Math.pow(10, decimalDifference));
}

/**
 * Convert amount in Rune Tokens to amount in Runes (as the token and rune might have different decimals)
 *
 * @returns The converted amount in the destination token's precision (as a bigint).
 *
 * @example
 * runeDecimals = 6
 * tokenDecimals = 18
 * tokenAmount = 1e10 (which is 10,000,000,000 in base units)
 *
 * - Calculate Decimal Difference:
 * decimalDifference = 18 - 6 = 12
 *
 * - Divide Transferred Token Amount by 10^12:
 * netRuneAmount = 1e10 / 10^12 = 1e10 / 1e12 = 1e-2 = 0.01
 */
export const getRuneAmount = (runeDecimals: number, tokenDecimals: number, tokenAmount: bigint): bigint => {
  if (tokenDecimals < runeDecimals) {
    throw new Error("Token decimals should be greater than or equal to rune decimals.");
  }
  const divisor = calculateDivisor(runeDecimals, tokenDecimals);
  return tokenAmount / divisor;
}

/**
 * Convert amount in Runes to amount in Rune Tokens.
 * @param runeDecimals
 * @param tokenDecimals
 * @param tokenAmount
 */
export const getTokenAmount = (runeDecimals: number, tokenDecimals: number, tokenAmount: bigint): bigint => {
  if (tokenDecimals < runeDecimals) {
    throw new Error("Token decimals should be greater than or equal to rune decimals.");
  }
  const divisor = calculateDivisor(runeDecimals, tokenDecimals);
  return tokenAmount * divisor;
}

/**
 * Use this function to convert a big integer value to scientific notation. ( easier to read )
 * @param bigIntValue
 * @returns {string}
 * @example
 * bigIntToScientificNotation(BigInt(100)) // 1e2
 */
export const bigIntToScientificNotation = (bigIntValue: bigint) => {
  const format = {
    notation: 'scientific',
    maximumFractionDigits: 20 // The default is 3, but 20 is the maximum supported by JS according to MDN.
  };
  // @ts-ignore
  return bigIntValue.toLocaleString('en-US', format);
}
export const xFailCase = (title: string) => `${title} (${xFail})`;
/**
 * Factory function to create test cases with fees for the `handlesRune` function.
 */
export const createHandlesFeesWithFeesTestCases = (): HandlesRuneWithFeeTestCaseProps[] => {
  const defaultPolicy: EvmToBtcTransferPolicy = {
    maxTokenAmount: ethers.parseUnits('1000', 18),
    minTokenAmount: 1,
    flatFeeBaseCurrency: 0,
    flatFeeTokens: 0,
    dynamicFeeTokens: 0,
  };

  // title, policyOverride, runeDecimals, amountToTransferDecimals, amountToTransfer, expectedTokenFee, baseCurrencyFee, isError
  const testCasesParams: [string, Partial<EvmToBtcTransferPolicy>, number, number, number, number?, number?, boolean?][] = [
    // Fees will be set in rune tokens base units or decimals
    [handlesRuneWithDiffDecimalsAndflatFeeTokens, {flatFeeTokens: 30}, 18, 18, 100],
    [handlesRuneWithDiffDecimalsAndflatFeeTokens, {flatFeeTokens: 10}, 23, 23, 100],
    [handlesRuneWithDiffDecimalsAndflatFeeTokens, {flatFeeTokens: 20}, 8, 18, 100],
    [handlesRuneWithDiffDecimalsAndDynamicFeeTokens, {dynamicFeeTokens: 300}, 8, 18, 100],
    [handlesRuneWithDiffDecimalsAndDynamicFeeTokens, {dynamicFeeTokens: 100}, 8, 10, 5],
    [handlesRuneWithDiffDecimalsAndDynamicFeeTokens, {dynamicFeeTokens: 100}, 8, 12, 1],
    [handlesRuneWithDiffDecimalsAndFlatFeeTokensAndDynamicFeeTokens, {
      flatFeeTokens: 1,
      dynamicFeeTokens: 100
    }, 8, 10, 5],
    [handlesRuneWithDiffDecimalsAndFlatFeeTokensAndDynamicFeeTokens, {
      flatFeeTokens: 1,
      dynamicFeeTokens: 150
    }, 8, 12, 1],
    [xFailCase(handlesRuneWithDiffDecimalsAndDynamicFeeTokens), {dynamicFeeTokens: 100}, 8, 7, 1],
    [xFailCase(handlesRuneWithDiffDecimalsAndDynamicFeeTokens), {dynamicFeeTokens: 100}, 8, 9, 1],
    [xFailCase(handlesRuneWithDiffDecimalsAndFlatFeeTokensAndDynamicFeeTokens), {
      flatFeeTokens: 1,
      dynamicFeeTokens: 100
    }, 6, 10, 1],
    [handlesRuneWithDiffDecimalsWithSmallAmountAndDynamicFeeTokens,{dynamicFeeTokens: 100}, 6, 13, 1],
    // ['', {}, 9, 10, 1],
    // ['',{}, 8, 9, 18],
    // ['',{}, 11, 6, 11],
  ];

  return testCasesParams.map((
    [
      title,
      policyOverrides,
      runeDecimals,
      amountToTransferDecimals,
      amountToTransfer,
      expectedTokenFee = 0,
      baseCurrencyFee = 0,
      isError = false
    ]) => {
    const policy: EvmToBtcTransferPolicy = {
      ...defaultPolicy,
      ...policyOverrides,
      maxTokenAmount: runeDecimals > 18 ? ethers.parseUnits('1000', runeDecimals) : defaultPolicy.maxTokenAmount,
      minTokenAmount: runeDecimals > 18 ? ethers.parseUnits('1', runeDecimals) : defaultPolicy.minTokenAmount,
    };
    return {
      title,
      policy,
      runeDecimals,
      amountToTransferDecimals,
      amountToTransfer: BigInt(amountToTransfer),
      expectedTokenFee: BigInt(expectedTokenFee),
      baseCurrencyFee: BigInt(baseCurrencyFee),
      isError
    };
  });
};

/**
 * Factory function to create test cases without fees for the `handlesRune` function.
 */
export const createHandlesFeesTestCases = (): HandlesRuneTestCaseProps[] => {
  const differentDecimalsCases: [number, number, number, number?, number?, boolean?][] = [
    // runeDecimals, amountToTransferDecimals, amountToTransfer, expectedTokenFee, baseCurrencyFee, isError
    [18, 18, 100],
    [23, 23, 100],
    [8, 18, 100],
    [8, 18, 1],
    [8, 10, 1],
    [8, 12, 1],
    [8, 9, 1, 0, undefined, true], // Pass undefined explicitly for baseCurrencyFee if not provided
    [8, 7, 1, 0, undefined, true],
    [9, 10, 1],
    [6, 10, 1, 0, undefined, true],
    [8, 9, 11, 1e9]
  ];
  return differentDecimalsCases.map((
    [
      runeDecimals,
      amountToTransferDecimals,
      amountToTransfer,
      expectedTokenFee = 0,
      baseCurrencyFee = 0,
      isError = false
    ]) => ({
    runeDecimals,
    amountToTransferDecimals,
    amountToTransfer: BigInt(amountToTransfer),
    expectedTokenFee: BigInt(expectedTokenFee),
    baseCurrencyFee: BigInt(baseCurrencyFee),
    isError
  }));
};

/**
 * Function to split the transferred amount and tokenFee from the fractional part of the amount
 * @param amount
 * @param runeDecimals
 * @param tokenDecimals
 */
export const extractFractionalAmount = (amount: bigint, runeDecimals: number, tokenDecimals: number): extractFractionalAmountProps => {
  const baseDiff = Number(tokenDecimals) - Number(runeDecimals);
  const divisor = baseDiff > 0 ? BigInt(Math.pow(10, baseDiff)) : BigInt(1);
  const transferredAmount = (amount / divisor) * divisor;
  const fractionalAmountAsTokenFee = amount - transferredAmount;
  return {fractionalAmountAsTokenFee};
}
