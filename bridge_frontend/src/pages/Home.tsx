import React from 'react';
import {useStore} from 'zustand';
import ethereumStore, {TokenBalance} from "../stores/useEthereumStore";
import {pick} from "ramda";
import Container from 'react-bootstrap/Container';
import Row from 'react-bootstrap/Row';
import Col from 'react-bootstrap/Col';
import Button from 'react-bootstrap/Button';
import {Form, Stack, Tab, Table, Tabs} from "react-bootstrap";
import {transferToBTC} from "../utils/contracts";


const Home = () => {
  const {provider, account, tokenBalances} = ethereumStore(
    state => pick(['provider', 'account', 'tokenBalances'], state)
  );
  return (
    <Container style={account && provider ? {} : {textAlign: 'center'}}>
      {
        account && provider && <TransferForm/>
      }
    </Container>
  );
}

export default Home;

export const TransferForm = () => {
  const {balance, tokenBalances, refreshTokenBalances} = useStore(ethereumStore);
  const [tabKey, setTabKey] = React.useState<string>('rune');
  React.useEffect(() => {
    // for 30seconds refresh token balances
    const interval = setInterval(() => {
      refreshTokenBalances();
    }, 30000);
    return () => clearInterval(interval);
  }, []);
  return (
    <Stack gap={3}>
      <Row style={{border: 'solid #1dc686', borderRadius: "10px"}}>
        <Tabs
          id="controlled-tab-example"
          activeKey={tabKey}
          onSelect={(k) => k && setTabKey(k)}
          className="mb-3"
        >
          <Tab eventKey="rune" title="RUNE -> RSK">
            <RuneTransferForm/>
          </Tab>
          <Tab eventKey="rsk" title="RSK -> RUNE">
            <RSKTransferForm/>
          </Tab>
        </Tabs>
      </Row>

      <Row>
        <Col md="12">
          <h3>Balances:</h3>
        </Col>
        <Col>
          <Table>
            <thead style={{textAlign: 'left'}}>
            <tr>
              <th>Token</th>
              <th>Balance</th>
            </tr>
            </thead>
            <tbody>
            <tr>
              <td>HARDHATETH</td>
              <td>{balance}</td>
            </tr>
            {
              tokenBalances.map((tokenBalance: any, index) => {
                return (
                  <tr key={`${tokenBalance.name}-${index}`}>
                    <td>{tokenBalance.symbol}</td>
                    <td>{tokenBalance.balance}</td>
                  </tr>
                )
              })
            }
            </tbody>
          </Table>
        </Col>
      </Row>
    </Stack>
  );
}

export const RuneTransferForm = () => {
  const {tokenBalances, account} = useStore(ethereumStore);
  const [depositAddress, setDepositAddress] = React.useState<string>('');
  const generateDepositAddress = async () => {
    const url = "/api/v1/runes/deposit-addresses/"
    const data = {"evm_address": account}
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      const error = await response.text();
      console.log('error: ', error);
      return;
    }

    const {deposit_address: depositAddress} = await response.json();
    setDepositAddress(depositAddress);
  }
  return (
    <Container>
      <Form>
        <Form.Group as={Row} className="mb-3" controlId="formTokenSelect">
          <Form.Label column sm={1}>Rune</Form.Label>
          <Col sm={11}>
            <Form.Select aria-label="Token">
              {
                tokenBalances.map((tokenBalance: any, index) => {
                  return (
                    <option key={`${tokenBalance.name}-${index}`}
                            defaultValue={tokenBalance.tokenContractAddress}>{tokenBalance.name}</option>
                  )
                })
              }
            </Form.Select>
          </Col>
        </Form.Group>
        <Form.Group as={Row} className="mb-3">
          <Form.Label column sm={1}>Deposit Address</Form.Label>
          <Col sm={11}>
            <Form.Control
              type="text"
              readOnly
              disabled
              defaultValue={depositAddress}
            />
          </Col>
        </Form.Group>
        <Form.Group className="mb-3">
          <Button variant="info" onClick={generateDepositAddress}>Generate deposit address</Button>
        </Form.Group>
      </Form>
    </Container>
  )
}

export const RSKTransferForm = () => {
  const {tokenBalances, runeBridgeContract, signer} = useStore(ethereumStore);
  const [selectedToken, setSelectedToken] = React.useState<TokenBalance>();
  const [amountToSend, setAmountToSend] = React.useState<string>('');
  const [receiver, setReceiver] = React.useState<string>('');
  const transferBTCHandler = async () => {
    const response = await transferToBTC(selectedToken?.tokenContractAddress, amountToSend, receiver, runeBridgeContract, signer);
  }
  return (
    <Container>
      <Form>
        <Form.Group as={Row} className="mb-3" controlId="formTokenSelect">
          <Form.Label column sm={1}>Rune</Form.Label>
          <Col sm={11}>
            <Form.Select
              aria-label="Token"
              onChange={(e) => {
                console.log('e: ', e.target.value);
                const selectedToken = tokenBalances.find((tokenBalance: any) => tokenBalance.name === e.target.value);
                setSelectedToken(selectedToken);
              }}
            >
              <option>Select Token</option>
              {
                tokenBalances.map((tokenBalance: any, index) => {
                  return (
                    <option key={`${tokenBalance.name}-${index}`}
                            defaultValue={tokenBalance.tokenContractAddress}>{tokenBalance.name}</option>
                  )
                })
              }
            </Form.Select>
          </Col>
        </Form.Group>
        <Form.Group as={Row} className="mb-3">
          <Form.Label column sm={1}>Balance (RSK)</Form.Label>
          <Col sm={11}>
            <Form.Control type="text" readOnly disabled defaultValue={selectedToken?.balance}/>
          </Col>
        </Form.Group>
        <Form.Group as={Row} className="mb-3">
          <Form.Label column sm={1}>Amount</Form.Label>
          <Col sm={11}>
            <Form.Control
              type="text"
              value={amountToSend}
              onChange={(e) => setAmountToSend(e.target.value)}
            />
          </Col>
        </Form.Group>
        <Form.Group as={Row} className="mb-3">
          <Form.Label column sm={1}>Receiver (BTC)</Form.Label>
          <Col sm={11}>
            <Form.Control type="text" placeholder="..." value={receiver} onChange={(e) => setReceiver(e.target.value)}/>
          </Col>
        </Form.Group>
        <Form.Group className="mb-3">
          <Button variant="info" onClick={transferBTCHandler}>Transfer</Button>
        </Form.Group>
      </Form>
    </Container>
  )
}
