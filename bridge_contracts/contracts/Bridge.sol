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
        uint256 indexed counter,
        address indexed to,
        uint256 amountWei,
        bytes32 btcTxId,
        uint256 btcTxVout
    );

    event TransferToBTC(
        uint256 indexed counter,
        address indexed from,
        uint256 amountWei,
        string btcAddress
    );

    event FederatorAdded(
        address indexed account
    );

    event FederatorRemoved(
        address indexed account
    );

    IPrecompiledMintingContract public precompiledMintingContract;
    IBTCAddressValidator public btcAddressValidator;
    uint256 public numRequiredSigners;
    address[] public federators;

    uint256 public numTransfersToBtc;
    uint256 public numTransfersFromBtc;
    // track procesed BTC->EVM transfers
    mapping(bytes32 => mapping(uint256 => bool)) public processedByBtcTxIdAndVout;

    modifier onlyFederator() {
        require(isFederator(msg.sender), "only federator");
        _;
    }

    constructor(
        IPrecompiledMintingContract _precompiledMintingContract,
        IBTCAddressValidator _btcAddressValidator,
        uint256 _numRequiredSigners,
        address[] memory _federators
    ) {
        precompiledMintingContract = _precompiledMintingContract;
        btcAddressValidator = _btcAddressValidator;
        numRequiredSigners = _numRequiredSigners;
        // check that there are no duplicates
        for (uint256 i = 0; i < _federators.length; i++) {
            for (uint256 j = i + 1; j < _federators.length; j++) {
                require(_federators[i] != _federators[j], "duplicate federator");
            }
        }
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
        numTransfersToBtc++;
        emit TransferToBTC(numTransfersToBtc, msg.sender, msg.value, btcAddress);
    }

    // Federator API
    // -------------

    /// @dev This is the "mint" function in the PRD
    function acceptTransferFromBtc(
        address payable to,
        uint256 amount,
        bytes32 btcTxId,
        uint256 btcTxVout,
        bytes[] memory _signatures
    )
    external
    onlyFederator
    nonReentrant
    {
        bytes32 signedMessageHash = ECDSA.toEthSignedMessageHash(
            getTransferFromBtcMessageHash(
                to,
                amount,
                btcTxId,
                btcTxVout
            )
        );
        uint256 numRequired = numRequiredSigners;

        address[] memory seen = new address[](_signatures.length);
        uint256 numConfirmations = 0;
        bool selfSigned = false;

        for (uint256 i = 0; i < _signatures.length; i++) {
            address recovered = ECDSA.recover(signedMessageHash, _signatures[i]);
            require(recovered != address(0), "recover failed");
            require(isFederator(recovered), "not a federator");
            for (uint256 j = 0; j < i; j++) {
                require(seen[j] != recovered, "already signed by federator");
            }
            seen[i] = recovered;
            numConfirmations++;
            if (recovered == msg.sender) {
                selfSigned = true;
            }
        }

        // if the sender's signature was not among signatures, add one confirmation for implicit self-sign
        if (!selfSigned) {
            numConfirmations++;
        }

        require(numConfirmations >= numRequired, "not enough confirmations");

        processedByBtcTxIdAndVout[btcTxId][btcTxVout] = true;
        precompiledMintingContract.mint(to, amount);
        numTransfersFromBtc++;
        emit TransferFromBTC(numTransfersFromBtc, to, amount, btcTxId, btcTxVout);
    }

    // Views/utilities
    // ---------------

    function getFederators()
    external
    view
    returns (address[] memory) {
        return federators;
    }

    function isFederator(
        address account
    )
    public
    view
    returns (bool)
    {
        for (uint256 i = 0; i < federators.length; i++) {
            if (federators[i] == account) {
                return true;
            }
        }
        return false;

    }

    function isProcessed(
        bytes32 btcTxId,
        uint256 btcTxVout
    )
    public
    view
    returns (bool)
    {
        return processedByBtcTxIdAndVout[btcTxId][btcTxVout];
    }

    function getTransferFromBtcMessageHash(
        address to,
        uint256 amount,
        bytes32 btcTxId,
        uint256 btcTxVout
    )
    public
    view
    returns (bytes32)
    {
        return keccak256(abi.encodePacked(
            "transferFromBtc:",
            address(this),
            ":",
            to,
            ":",
            amount,
            ":",
            btcTxId,
            ":",
            btcTxVout
        ));
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

    function addFederator(
        address account
    )
    external
    onlyOwner
    {
        require(!isFederator(account), "already a federator");
        federators.push(account);
        emit FederatorAdded(account);
    }

    function removeFederator(
        address account
    )
    external
    onlyOwner
    {
        require(isFederator(account), "not a federator");
        uint256 index = 0;
        while (federators[index] != account) {
            index++;
        }
        federators[index] = federators[federators.length - 1];
        federators.pop();
        emit FederatorRemoved(account);
    }

    function setNumRequiredSigners(
        uint256 _numRequiredSigners
    )
    external
    onlyOwner
    {
        require(_numRequiredSigners <= federators.length, "too many required signers");
        numRequiredSigners = _numRequiredSigners;
    }
}
