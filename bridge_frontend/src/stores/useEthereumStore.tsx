import {create, createStore} from "zustand";
import {ethers} from "ethers";
import runeBridgeABI from "../abi/RuneBridge.json";

interface TokenBalance {
  symbol: string;
  balance: string;
  name: string;
  tokenContractAddress: string;
}

interface EthereumState {
  provider: ethers.BrowserProvider | null;
  signer: ethers.Signer | null;
  account: string | null;
  balance: string | null;
  tokenBalances: Array<TokenBalance>;
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
  tokenBalances: [],
  chainId: null,
  contract: null,
  newBlockSubscriptionId: [],
  subscriptionId: null,
  isMetaMaskInstalled: false,
  isLoadingMetaMask: true,
  connectMetamask: async () => {
    const {ethereum} = window;
    if (ethereum) {
      try {
        const accounts = await ethereum.request({method: 'eth_requestAccounts'});
        const chainId = await ethereum.request({method: 'eth_chainId'});
        const parsedChainId = ethers.formatUnits(chainId, 0);

        const webProvider = new ethers.BrowserProvider(ethereum);
        const webSigner = await webProvider.getSigner();
        const balance = await ethereum.request({
          method: 'eth_getBalance',
          params: [accounts[0], 'latest']
        });

        const tokenABI = [
          "function balanceOf(address) view returns (uint)",
          "function symbol() view returns (string)",
          "function name() view returns (string)",
          "function decimals() view returns (uint)"
        ]
        const tokenBalances: Array<TokenBalance> = [];

        const runeBridgeAddress = process.env.REACT_APP_RUNE_BRIDGE_CONTRACT_ADDRESS!;
        const runeBridgeContract = new ethers.Contract(runeBridgeAddress, runeBridgeABI, webProvider);
        const listTokens = await runeBridgeContract.listTokens();

        for (const tokenAddress of listTokens) {
          const tokenContract = new ethers.Contract(tokenAddress, tokenABI, webProvider);
          const balance = await tokenContract.balanceOf(accounts[0]);
          const symbol = await tokenContract.symbol();
          const name = await tokenContract.name();
          const decimals = await tokenContract.decimals();
          tokenBalances.push({
            symbol: symbol,
            balance: ethers.formatUnits(balance, decimals),
            name: name,
            tokenContractAddress: tokenAddress
          });
        }
        set((
          state: EthereumState
        ) => ({
          provider: webProvider,
          signer: webSigner,
          account: accounts[0],
          chainId: parsedChainId,
          balance: ethers.formatEther(balance),
          tokenBalances: tokenBalances,
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
