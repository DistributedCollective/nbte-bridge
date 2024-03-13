import React from 'react';
import useEthereumStore from "../stores/useEthereumStore";
import {useStore} from "zustand";
import ethereumStore from "../stores/useEthereumStore";
import {Image, Navbar} from "react-bootstrap";
import Container from "react-bootstrap/Container";
import Button from "react-bootstrap/Button";
import sovrynLogo from "../assets/logo/sovryn-logo.svg";
import './TopNav.css';

const TopNav = () => {
  const {account, chainId} = useEthereumStore();
  return (
    <Navbar expand="lg" className="top-nav">
      <Container>
        <Navbar.Brand>
          <div className="top-nav-brand">
            <h2>
              <Image src={sovrynLogo} className="logo" alt="Sovryn Bridge"/>
            </h2>
            <h2>
              Rune Bridge
            </h2>
          </div>
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

export interface MetamaskConnecButtonProps {
  text?: string;
  size?: 'lg' | 'sm' | undefined;
}
export const MetamaskConnectButton = (props: MetamaskConnecButtonProps) => {
  const {connectMetamask} = useStore(ethereumStore);
  return (
    <Button
      className="login-button"
      size={props.size ?? 'lg'}
      onClick={connectMetamask}>
      {props.text ?? 'Connect wallet'}
    </Button>
  );
}
