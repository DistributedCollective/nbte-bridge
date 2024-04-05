// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

import "../shared/NBTEBridgeAccessControllable.sol";
import "../shared/IBTCAddressValidator.sol";
import "./RuneSideToken.sol";


contract RuneBridge is NBTEBridgeAccessControllable {
    event RuneTransferToBtc(
        uint256 indexed counter,
        address indexed from,
        address token,
        string rune,  // TODO: use uint256
        uint256 amountWei,
        string receiverBtcAddress
    );

    event RuneTransferFromBtc(
        uint256 indexed counter,
        address indexed to,
        address token,
        string rune,
        uint256 amountWei,
        bytes32 btcTxId,
        uint256 btcTxVout
    );

    IBTCAddressValidator public btcAddressValidator;

    uint256 public numTransfersTotal;

    // TODO: support for multiple tokens
    RuneSideToken private _runeSideToken;
    string private _rune = "MYRUNEISGOODER";
    bytes32 private _runeHash = keccak256(abi.encodePacked("MYRUNEISGOODER"));


    constructor(
        address _accessControl,
        address _btcAddressValidator
    )
    NBTEBridgeAccessControllable(_accessControl)
    {
        btcAddressValidator = IBTCAddressValidator(_btcAddressValidator);
        _runeSideToken = new RuneSideToken("MYRUNEISGOODER", "R");
    }

    // Public API
    // ----------

    function transferToBtc(
        address token,
        uint256 amountWei,
        string calldata receiverBtcAddress
    )
    external
    {
        require(btcAddressValidator.isValidBtcAddress(receiverBtcAddress), "invalid BTC address");
        require(token == address(_runeSideToken), "token not registered");
        require(amountWei > 0, "amount must be greater than 0");

        string memory rune = getRuneByToken(token);

        RuneSideToken(token).burn(msg.sender, amountWei);

        numTransfersTotal++;
        emit RuneTransferToBtc(
            numTransfersTotal,
            msg.sender,
            token,
            rune,
            amountWei,
            receiverBtcAddress
        );
    }

    function getTokenByRune(string memory rune) public view returns (address) {
        require(keccak256(abi.encodePacked(rune)) == _runeHash, "rune not found");
        return address(_runeSideToken);
    }

    function getRuneByToken(address token) public view returns (string memory) {
        require(token == address(_runeSideToken), "token not found");
        return _rune;
    }

    function listTokens() public view returns (address[] memory) {
        address[] memory tokens = new address[](1);
        tokens[0] = address(_runeSideToken);
        return tokens;
    }

    // Federator API
    // -------------

    function acceptTransferFromBtc(
        address to,
        string memory rune,
        uint256 amountWei,
        bytes32 btcTxId,
        uint256 btcTxVout,
        bytes[] memory signatures
    )
    external
    {
        // validate signatures. this also checks that the sender is a federator
        accessControl.checkFederatorSignaturesWithImplicitSelfSign(
            keccak256("foo"), // TODO
            signatures,
            msg.sender
        );

        // TODO: validate not processed

        address token = getTokenByRune(rune);
        require(token != address(0), "token not found");

        RuneSideToken(token).mint(to, amountWei);

        numTransfersTotal++;
        emit RuneTransferFromBtc(
            numTransfersTotal,
            to,
            token,
            rune,
            amountWei,
            btcTxId,
            btcTxVout
        );
    }

    // Owner API
    // ---------

    // TODO: another temporary thing
    function registerRune(
        string memory rune,
        string memory symbol
    )
    external
    onlyAdmin
    {
        _rune = rune;
        _runeHash = keccak256(abi.encodePacked(rune));
        _runeSideToken = new RuneSideToken(rune, symbol);
    }
}
