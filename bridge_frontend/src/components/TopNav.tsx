import React from 'react';
import useEthereumStore from "../stores/useEthereumStore";
import {useStore} from "zustand";
import ethereumStore from "../stores/useEthereumStore";
import {Navbar} from "react-bootstrap";
import Container from "react-bootstrap/Container";
import Button from "react-bootstrap/Button";
import './TopNav.css';

const TopNav = () => {
  const {account, chainId} = useEthereumStore();
  return (
    <Navbar expand="lg" className="top-nav">
      <Container>
        <Navbar.Brand>
          <h2>Rune Bridge</h2>
        </Navbar.Brand>
        <Navbar.Collapse
          className="justify-content-end"
        >
          {
            account ? (
              <Navbar.Text>
                <p>{account}</p>
                <p>ChainId: {chainId}</p>
              </Navbar.Text>
            ) : (
              <MetamaskConnectButton/>
            )
          }
        </Navbar.Collapse>
      </Container>
    </Navbar>
  );
};

export default TopNav;

export const MetamaskConnectButton = () => {
  const {connectMetamask} = useStore(ethereumStore);
  return (
    <Button
      className="login-button"
      onClick={connectMetamask}>
      Connect Metamask
    </Button>
  );
}
