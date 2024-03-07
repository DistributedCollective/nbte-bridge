import {ethers} from "ethers";

export const transferToBTC = async (tokenAddress: string | undefined, amount: string, receiverBtcAddress: string, contract: ethers.Contract | null, signer: ethers.Signer | null) => {
  if (!contract) {
    throw new Error('Contract not found');
  }
  if (!signer) {
    throw new Error('Signer not found');
  }
  const amountWei = ethers.parseEther(amount);
  const tx = await contract.connect(signer).getFunction('transferToBtc')(tokenAddress, amountWei, receiverBtcAddress)
  const txReceipt = await tx.wait();
  return txReceipt;
}
