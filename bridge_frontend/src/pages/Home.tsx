import React from 'react';
import {useStore} from 'zustand';
import ethereumStore from "../stores/useEthereumStore";
import {pick} from "ramda";

export const AccountInfo = () => {
  const {balance, provider, chainId} = useStore(ethereumStore);
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'row',
      padding: '30px',
      justifyContent: 'space-evenly',
    }}>
      <div style={{
        backgroundColor: 'antiquewhite',
      }}>
        <p>ChainId: {chainId}</p>
        <p>Balances: {balance}</p>
      </div>

      <div style={{
        backgroundColor: 'antiquewhite',
      }}>
        <form>
          <h1>Transfer</h1>
        </form>
      </div>

    </div>
  );
}
export const MetamaskConnectButton = () => {
  const {connectMetamask} = useStore(ethereumStore);
  return (
    <button onClick={connectMetamask}>Connect MetaMask</button>
  );
}

const Home = () => {
  const {provider, account} = ethereumStore(
    state => pick(['provider', 'account'], state)
  );
  return (
    <div>
      <div style={account && provider ? {} : {textAlign: 'center'}}>
        {
          account && provider ? <AccountInfo/> :
            <MetamaskConnectButton/>
        }
      </div>
    </div>
  );
}

export default Home;
