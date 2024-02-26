// use the Apollo client to query the GraphQL API
// Language: typescript
// Path: bridge/bridge_frontend/src/App.tsx

import React from 'react';
import logo from './logo.svg';
import './App.css';
import detectEthereumProvider from '@metamask/detect-provider';
import {pick} from "ramda";
import Home from "./pages/Home";
import TopNav from "./components/TopNav";

declare global {
  interface Window {
    ethereum: any;
  }
}

const App = () => {
  const [hasProvider, setHasProvider] = React.useState(false)
  React.useEffect(() => {
    detectEthereumProvider().then((provider) => {
      if (provider) {
        setHasProvider(true)
      } else {
        setHasProvider(false)
      }
    })
  }, [])

  return (
    <div>
      <TopNav/>
      {hasProvider ? <Home/> : <div>Install MetaMask</div>}
    </div>
  );
};

export default App;
