import {create, createStore} from "zustand";
import {ethers} from "ethers";

interface EthereumState {
  provider: ethers.BrowserProvider | null;
  signer: ethers.Signer | null;
  account: string | null;
  balance: string | null;
  chainId: string | null;
  contract: ethers.Contract | null;
  isMetaMaskInstalled: boolean;
  isLoadingMetaMask: boolean;
  connectMetamask: () => void;
  setProvider: (provider: ethers.BrowserProvider) => void;
  setSigner: (signer: ethers.Signer) => void;
  setAccount: (account: string) => void;
  setBalance: (balance: string) => void;
  setChainId: (chainId: string) => void;
  setContract: (contract: ethers.Contract) => void;
  setIsMetaMaskInstalled: (isMetaMaskInstalled: boolean) => void;
  setIsLoadingMetaMask: (isLoadingMetaMask: boolean) => void;
}

const ethereumStore = create<EthereumState>((set) => ({
  provider: null,
  signer: null,
  account: null,
  balance: null,
  chainId: null,
  contract: null,
  newBlockSubscriptionId: [],
  subscriptionId: null,
  isMetaMaskInstalled: false,
  isLoadingMetaMask: true,
  connectMetamask: async () => {
    const {ethereum} = window;
    // const contractAddress = process.env.PUBLIC_CONTRACT_ADDRESS;
    // const contractABI = Contract.abi;
    if (ethereum) {
      try {
        const accounts = await ethereum.request({method: 'eth_requestAccounts'});
        const chainId = await ethereum.request({method: 'eth_chainId'});
        const webProvider = new ethers.BrowserProvider(ethereum);
        const webSigner = await webProvider.getSigner();
        const balance = await ethereum.request({
          method: 'eth_getBalance',
          params: [accounts[0], 'latest']
        });
        console.log("signer: ", webSigner);
        set((
          state: EthereumState
        ) => ({
          provider: webProvider,
          signer: webSigner,
          account: accounts[0],
          chainId: chainId,
          balance: ethers.formatEther(balance),
        }));
      } catch (e) {
        console.error(e)
      }
    }
  },
  setChainId: (chainId: string) => set(() => ({chainId})),
  setProvider: (provider: ethers.BrowserProvider) => set(() => ({provider})),
  setSigner: (signer: ethers.Signer) => set(() => ({signer})),
  setAccount: (account: string) => set(() => ({account})),
  setBalance: (balance: string) => set(() => ({balance})),
  setContract: (contract: ethers.Contract) => set(() => ({contract})),
  setIsMetaMaskInstalled: (isMetaMaskInstalled: boolean) => set(() => ({isMetaMaskInstalled})),
  setIsLoadingMetaMask: (isLoadingMetaMask: boolean) => set(() => ({isLoadingMetaMask})),
}));

export default ethereumStore
