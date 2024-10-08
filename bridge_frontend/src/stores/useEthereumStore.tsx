import {create, createStore} from "zustand";
import {ethers} from "ethers";
import runeBridgeABI from "../abi/RuneBridge.json";

export interface TokenBalance {
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
  refreshTokenBalances: () => void;
  runeBridgeContract: ethers.Contract | null;
}

const TOKEN_ABI = [
  "function balanceOf(address) view returns (uint)",
  "function symbol() view returns (string)",
  "function name() view returns (string)",
  "function decimals() view returns (uint)"
]

const ethereumStore = create<EthereumState>((set, get) => ({
  provider: null,
  signer: null,
  account: null,
  balance: null,
  tokenBalances: [],
  chainId: null,
  contract: null,
  runeBridgeContract: null,
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

        const tokenBalances: Array<TokenBalance> = [];

        const runeBridgeAddress = process.env.REACT_APP_RUNE_BRIDGE_CONTRACT_ADDRESS!;
        const runeBridgeContract = new ethers.Contract(runeBridgeAddress, runeBridgeABI, webProvider);
        const listTokens = await runeBridgeContract.listTokens();

        for (const tokenAddress of listTokens) {
          const tokenContract = new ethers.Contract(tokenAddress, TOKEN_ABI, webProvider);
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
          runeBridgeContract: runeBridgeContract,
        }));
      } catch (e) {
        console.error(e)
      }
    }
  },
  refreshTokenBalances: async () => {
    const {provider, runeBridgeContract, account} = get();
    const tokenBalances: Array<TokenBalance> = [];
    const listTokens = await runeBridgeContract?.listTokens();
    for (const tokenAddress of listTokens) {
      const tokenContract = new ethers.Contract(tokenAddress, TOKEN_ABI, provider);
      const balance = await tokenContract.balanceOf(account);
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
    set(() => ({tokenBalances}));
  },
}));

export default ethereumStore
