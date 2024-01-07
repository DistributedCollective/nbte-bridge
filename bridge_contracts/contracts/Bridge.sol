// SPDX-License-Identifier: MIT
pragma solidity ^0.8.9;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Address.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";


contract Bridge is Ownable, ReentrancyGuard {
    using Address for address payable;

    event TransferFromBTC(
        address indexed to,
        uint256 amountWei,
        bytes32 btcTxHash,
        uint256 btcTxVout
    );

    event TransferToBTC(
        address indexed from,
        uint256 amountWei,
        string btcAddress
    );

    constructor() {
    }

    function acceptTransferFromBtc(
        address payable to,
        uint256 amount,
        bytes32 btcTxHash,
        uint256 btcTxVout
    )
    external
    onlyOwner
    nonReentrant
    {
        to.sendValue(amount);
        emit TransferFromBTC(to, amount, btcTxHash, btcTxVout);
    }

    function transferToBtc(
        string calldata btcAddress
    )
    external
    payable
    nonReentrant
    {
        // TODO: validate BTC address
        emit TransferToBTC(msg.sender, msg.value, btcAddress);
    }

    // TODO: these are to be removed as the mint interface will be used
    event Funded(address indexed by, uint256 amount);
    function fund()
    external
    payable
    onlyOwner
    {
        emit Funded(msg.sender, msg.value);
    }
    // /end temporary API
}
