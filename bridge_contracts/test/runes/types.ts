import {BigNumberish, Contract} from "ethers";

export type ContractProps = {
  runeBridgeContract?: Contract;
  runeToken?: Contract;
}
export type TransferPolicy = {
  tokenAddress?: string;
  maxTokenAmount: BigNumberish;
  minTokenAmount: BigNumberish;
  flatFeeBaseCurrency: BigNumberish;
  flatFeeTokens: BigNumberish;
  dynamicFeeTokens: BigNumberish;
}
export type EvmToBtcTransferPolicy = TransferPolicy & ContractProps;

export type TransferToBtcAndExpectEventProps = {
  tokenAddress: string;
  btcAddress: string;
  transferAmount: BigNumberish;
  emit: { contract: Contract, eventName: string };
  args: {
    counter: number,
    from: string,
    token: string,
    rune: BigNumberish,
    transferredTokenAmount: BigNumberish,
    netRuneAmount: BigNumberish,
    receiverBtcAddress: string,
    baseCurrencyFee: BigNumberish,
    tokenFee: BigNumberish,
  }
} & ContractProps;

export type HandlesRuneTestCaseProps = {
  runeDecimals: number;
  amountToTransferDecimals: number;
  amountToTransfer: bigint;
  expectedTokenFee: bigint;
  baseCurrencyFee: bigint;
  isError: boolean;
};

export type HandlesRuneWithFeeTestCaseProps = HandlesRuneTestCaseProps & {
  title: string;
  policy: EvmToBtcTransferPolicy;
}
