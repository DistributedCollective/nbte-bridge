import {getStorageAt, setStorageAt} from "@nomicfoundation/hardhat-network-helpers";
import {ethers} from 'hardhat';
import {BigNumberish, Contract, Signer} from 'ethers';
import {expect} from "chai";
import {EvmToBtcTransferPolicy, ExpectedEmitArgsProps} from "./types";

const RUNE_TOKEN_BALANCE_MAPPING_SLOT = 0;
const RUNE_TOKEN_TOTAL_SUPPLY_SLOT = 2;
export const reasonRuneRegistrationRequestsDisabled = 'rune registration requests disabled';
export const reasonRegistrationNotRequested = 'registration not requested';
export const reasonRuneAlreadyRegistered = 'rune already registered';

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
export const setEvmToBtcTransferPolicy = async ({
                                                  runeBridgeContract,
                                                  tokenAddress,
                                                  dynamicFeeTokens,
                                                  flatFeeTokens,
                                                  minTokenAmount,
                                                  maxTokenAmount,
                                                  flatFeeBaseCurrency
                                                }: EvmToBtcTransferPolicy): Promise<Contract> => {
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
 * @param {ExpectedEmitArgsProps} params - The parameters for the function.
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
export const expectedEmitWithArgs = async ({runeBridgeContract, tokenAddress, btcAddress, transferAmount, emit, args}: ExpectedEmitArgsProps): Promise<any> => {
  return expect(
    runeBridgeContract.transferToBtc(
    tokenAddress,
    transferAmount,
    btcAddress,
    {value: args.baseCurrencyFee}
  )).to.emit(
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
    return await Promise.all(federators.map(federator=> {
      return federator.signMessage(hashBytes)
    }));
}
export const transferToBTC = (runeBridge: Contract, tokenAddress: string, amount: BigNumberish, btcAddress: string) => {
  return runeBridge.transferToBtc(tokenAddress, amount, btcAddress);
}
