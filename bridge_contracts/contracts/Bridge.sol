// SPDX-License-Identifier: MIT
pragma solidity ^0.8.9;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "./IBTCAddressValidator.sol";
import "./IPrecompiledMintingContract.sol";


/// @dev This is the Bridge contract from the PRD. It deviates from the spec in a couple of ways:
/// - "mint" and "redeem" are renamed to "acceptTransferFromBtc" and "transferToBtc" respectively
/// - There's no separate multisig contract that acts as the issuer -- instead, multisig functionality is
///   built directly in the contract. This allows for better validation
/// TODO: make upgradeable
contract Bridge is Ownable, ReentrancyGuard {
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

    IPrecompiledMintingContract public precompiledMintingContract;
    IBTCAddressValidator public btcAddressValidator;
    uint256 public numRequiredSigners;
    address[] public federators;

    constructor(
        IPrecompiledMintingContract _precompiledMintingContract,
        IBTCAddressValidator _btcAddressValidator,
        uint256 _numRequiredSigners,
        address[] memory _federators
    ) {
        precompiledMintingContract = _precompiledMintingContract;
        btcAddressValidator = _btcAddressValidator;
        numRequiredSigners = _numRequiredSigners;
        federators = _federators;
    }


    // Public API
    // ----------

    function transferToBtc(
        string calldata btcAddress
    )
    external
    payable
    nonReentrant
    {
        require(btcAddressValidator.isValidBtcAddress(btcAddress), "invalid btc address");
        payable(0).transfer(msg.value);  // burn base currency
        emit TransferToBTC(msg.sender, msg.value, btcAddress);
    }

    function getFederators()
    external
    view
    returns (address[] memory) {
        return federators;
    }

    // Federator API
    // -------------

    /// @dev This is the "mint" function in the PRD
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
        precompiledMintingContract.mint(to, amount);
        emit TransferFromBTC(to, amount, btcTxHash, btcTxVout);
    }

    // Owner API
    // ---------

    function setPrecompiledMintingContract(
        IPrecompiledMintingContract _precompiledMintingContract
    )
    external
    onlyOwner
    {
        precompiledMintingContract = _precompiledMintingContract;
    }

    function setBtcAddressValidator(
        IBTCAddressValidator _btcAddressValidator
    )
    external
    onlyOwner
    {
        btcAddressValidator = _btcAddressValidator;
    }
}
