// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

import "../shared/NBTEBridgeAccessControllable.sol";
import "../shared/IBTCAddressValidator.sol";
import {RuneToken} from "./RuneToken.sol";


contract RuneBridge is NBTEBridgeAccessControllable {
    event RuneTransferToBtc(
        uint256 counter,
        address indexed from,
        address indexed token,
        uint256 indexed rune,
        uint256 transferredTokenAmount,
        uint256 netRuneAmount,
        string receiverBtcAddress
    );

    event RuneTransferFromBtc(
        uint256 counter,
        address indexed to,
        address indexed token,
        uint256 indexed rune,
        uint256 amountWei,
        bytes32 btcTxId,
        uint256 btcTxVout
    );

    event RuneRegistered(
        uint256 counter,
        uint256 rune,
        address token
    );

    IBTCAddressValidator public btcAddressValidator;

    uint256 public numTransfersTotal;

    mapping(uint256 => address) public tokensByRune;
    mapping(address => uint256) public runesByToken;
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
        RuneToken token,
        uint256 amountWei,
        string calldata receiverBtcAddress
    )
    external
    {
        require(amountWei > 0, "amount must be greater than 0");

        uint256 rune = token.rune();
        require(isRuneRegistered(rune), "rune not registered");

        require(btcAddressValidator.isValidBtcAddress(receiverBtcAddress), "invalid BTC address");

        // TODO: use an approve - transfer - burn pattern
        // burning from anyone is just fishy
        token.burn(msg.sender, amountWei);

        // this validates that the amount is not too precise
        uint256 netRuneAmount = token.getRuneAmount(amountWei);

        numTransfersTotal++;
        emit RuneTransferToBtc(
            numTransfersTotal,
            msg.sender,
            address(token),
            rune,
            amountWei,
            netRuneAmount,
            receiverBtcAddress
        );
    }

    function isRuneRegistered(uint256 rune) public view returns (bool) {
        return tokensByRune[rune] != address(0);
    }

    function numRunesRegistered() public view returns (uint256) {
        return runeTokens.length;
    }

    function getTokenByRune(uint256 rune) public view returns (address token) {
        token = tokensByRune[rune];
        require(token != address(0), "rune not found");
    }

    function getRuneByToken(address token) public view returns (uint256 rune) {
        rune = runesByToken[token];
        require(rune != 0, "token not found");
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
        uint256 rune,
        uint256 runeAmount,
        bytes32 btcTxId,
        uint256 btcTxVout,
        bytes[] memory signatures
    )
    external
    {
        // validate signatures. this also checks that the sender is a federator
        bytes32 messageHash = getAcceptTransferFromBtcMessageHash(
            to,
            rune,
            runeAmount,
            btcTxId,
            btcTxVout
        );
        accessControl.checkFederatorSignaturesWithImplicitSelfSign(
            messageHash,
            signatures,
            msg.sender
        );

        // TODO: validate not processed

        RuneToken token = RuneToken(getTokenByRune(rune));  // this validates that it's registered

        uint256 tokenAmount = token.getTokenAmount(runeAmount);
        token.mint(to, tokenAmount);

        numTransfersTotal++;
        emit RuneTransferFromBtc(
            numTransfersTotal,
            to,
            address(token),
            rune,
            tokenAmount,
            btcTxId,
            btcTxVout
        );
    }

    function getAcceptTransferFromBtcMessageHash(
        address to,
        uint256 rune,
        uint256 runeAmount,
        bytes32 btcTxId,
        uint256 btcTxVout
    )
    public
    view
    returns (bytes32)
    {
        return keccak256(abi.encodePacked(
            "acceptTransferFromBtc:",
            address(this),
            ":",
            to,
            ":",
            rune,
            ":",
            runeAmount,
            ":",
            btcTxId,
            ":",
            btcTxVout
        ));
    }

    function numRequiredFederators() public view returns (uint256) {
        return accessControl.numRequiredFederators();
    }

    // Owner API
    // ---------

    function registerRune(
        string memory name,
        string memory symbol,
        uint256 rune,
        uint8 runeDivisibility
    )
    external
    onlyAdmin
    {
        require(!isRuneRegistered(rune), "rune already registered");
        require(rune <= type(uint128).max, "rune number too large");
        RuneToken token = new RuneToken(
            name,
            symbol,
            rune,
            runeDivisibility
        );
        tokensByRune[rune] = address(token);
        runesByToken[address(token)] = rune;
        runeTokens.push(address(token));
        emit RuneRegistered(
            runeTokens.length,
            rune,
            address(token)
        );
    }
}
