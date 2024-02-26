import React from 'react';
import useEthereumStore from "../stores/useEthereumStore";

const TopNav = () => {
  const {account} = useEthereumStore();

  return (
    <nav style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '20px',
      backgroundColor: 'lightgray',
      marginBottom: '20px',
    }}>
      <div>
        <h2>Rune Brigde DApp</h2>
      </div>
      <div>
        {
          account && <p>{account}</p>
        }
      </div>
    </nav>
  );
};

export default TopNav;
