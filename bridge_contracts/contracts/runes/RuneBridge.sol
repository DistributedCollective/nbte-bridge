// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

import "../shared/NBTEBridgeAccessControllable.sol";
import "../shared/IBTCAddressValidator.sol";
import {RuneToken} from "./RuneToken.sol";


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

    mapping(string => address) public tokensByRune;
    mapping(address => string) public runesByToken;
    address[] public runeTokens;

    constructor(
        address _accessControl,
        address _btcAddressValidator
    )
    NBTEBridgeAccessControllable(_accessControl)
    {
        btcAddressValidator = IBTCAddressValidator(_btcAddressValidator);
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
        require(amountWei > 0, "amount must be greater than 0");

        string memory rune = getRuneByToken(token);  // this validates it too

        require(btcAddressValidator.isValidBtcAddress(receiverBtcAddress), "invalid BTC address");

        // TODO: use an approve - transfer - burn pattern
        // burning from anyone is just fishy
        RuneToken(token).burn(msg.sender, amountWei);

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

    function isRuneRegistered(string memory rune) public view returns (bool) {
        return tokensByRune[rune] != address(0);
    }

    function numRunesRegistered() public view returns (uint256) {
        return runeTokens.length;
    }

    function getTokenByRune(string memory rune) public view returns (address) {
        address token = tokensByRune[rune];
        require(token != address(0), "rune not found");
        return token;
    }

    function getRuneByToken(address token) public view returns (string memory) {
        string memory rune = runesByToken[token];
        require(bytes(rune).length > 0, "token not found");
        return rune;
    }

    function listTokens() public view returns (address[] memory) {
        return runeTokens;
    }

    function paginateTokens(uint256 start, uint256 count) public view returns (address[] memory) {
        if (start >= runeTokens.length) {
            return new address[](0);
        }
        uint256 end = start + count;
        if (end > runeTokens.length) {
            end = runeTokens.length;
        }
        address[] memory result = new address[](end - start);
        for (uint256 i = start; i < end; i++) {
            result[i - start] = runeTokens[i];
        }
        return result;
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

        address token = getTokenByRune(rune);  // this validates that it exists

        RuneToken(token).mint(to, amountWei);

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

    function registerRune(
        string memory rune,
        string memory symbol
    )
    external
    onlyAdmin
    {
        require(!isRuneRegistered(rune), "rune already registered");
        RuneToken token = new RuneToken(rune, symbol);
        tokensByRune[rune] = address(token);
        runesByToken[address(token)] = rune;
        runeTokens.push(address(token));
        // TODO: emit event, etc
    }
}
