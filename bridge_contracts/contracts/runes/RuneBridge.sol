// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

import "../shared/NBTEBridgeAccessControllable.sol";
import "../shared/IBTCAddressValidator.sol";
import {Freezable} from "../shared/Freezable.sol";
import {Pausable} from "@openzeppelin/contracts/security/Pausable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Address} from "@openzeppelin/contracts/utils/Address.sol";
import {RuneToken} from "./RuneToken.sol";


contract RuneBridge is NBTEBridgeAccessControllable, Freezable, Pausable {
    using SafeERC20 for IERC20;
    using SafeERC20 for RuneToken;
    using Address for address payable;

    event RuneTransferToBtc(
        uint256 counter,
        address indexed from,
        address indexed token,
        uint256 indexed rune,
        uint256 transferredTokenAmount,
        uint256 netRuneAmount,
        string receiverBtcAddress,
        uint256 baseCurrencyFee,
        uint256 tokenFee
    );

    event RuneTransferFromBtc(
        uint256 counter,
        address indexed to,
        address indexed token,
        uint256 indexed rune,
        uint256 tokenAmount,
        bytes32 btcTxId,
        uint256 btcTxVout
    );

    event RuneRegistered(
        uint256 counter,
        uint256 rune,
        address token
    );

    struct EvmToBtcTransferPolicy {
        uint256 maxTokenAmount;  // if this is zero, the transfer policy is treated as unset
        uint256 minTokenAmount;
        uint256 flatFeeBaseCurrency;
        uint256 flatFeeTokens;
        uint256 dynamicFeeTokens;  // base unit is 0.01 %
    }

    event EvmToBtcTransferPolicyChanged(
        address indexed token, // 0x0 for default policy
        uint256 maxTokenAmount,
        uint256 minTokenAmount,
        uint256 flatFeeBaseCurrency,
        uint256 flatFeeTokens,
        uint256 dynamicFeeTokens
    );

    /// @dev Denominator for the dynamic fee. uint16; 0.01 % granularity
    uint256 public constant DYNAMIC_FEE_DIVISOR = 10_000;

    IBTCAddressValidator public btcAddressValidator;

    uint256 public numTransfersTotal;

    mapping(uint256 => address) public tokensByRune;
    mapping(address => uint256) public runesByToken;
    address[] public runeTokens;

    mapping(address => EvmToBtcTransferPolicy) public evmToBtcTransferPoliciesByToken;  // 0x0 for default policy

    constructor(
        address _accessControl,
        address _btcAddressValidator
    )
    NBTEBridgeAccessControllable(_accessControl)
    {
        btcAddressValidator = IBTCAddressValidator(_btcAddressValidator);
        // set default transfer policy
        _setEvmToBtcTransferPolicy(
            address(0),
            1_000_000 ether,
            1,
            0.0003 ether, // 30k sat
            0,
            40  // 0.4%
        );
    }

    // Public API
    // ----------

    function transferToBtc(
        RuneToken token,
        uint256 tokenAmount,
        string calldata receiverBtcAddress
    )
    external
    payable
    whenNotPaused
    {
        require(tokenAmount > 0, "amount must be greater than 0");

        uint256 rune = token.rune();
        require(isRuneRegistered(rune), "rune not registered");

        require(btcAddressValidator.isValidBtcAddress(receiverBtcAddress), "invalid BTC address");

        EvmToBtcTransferPolicy memory policy = getEvmToBtcTransferPolicy(address(token));
        require(tokenAmount >= policy.minTokenAmount, "amount too low");
        require(tokenAmount <= policy.maxTokenAmount, "amount too high");
        require(msg.value == policy.flatFeeBaseCurrency, "incorrect base currency fee (either overpaying or underpaying");

        uint256 tokenFee = policy.flatFeeTokens + (tokenAmount * policy.dynamicFeeTokens / DYNAMIC_FEE_DIVISOR);
        require(tokenAmount >= tokenFee, "token amount less than fees");

        // NOTE: converting between token and rune amounts might result in truncating of decimals
        // if the rune has less decimals than the token. This is taken into account in the double conversions here,
        // and the truncated amount is treated as transfer fee
        uint256 netRuneAmount = token.getRuneAmount(tokenAmount - tokenFee);
        require(netRuneAmount > 0, "received net rune amount is zero");
        uint256 netTokenAmount = token.getTokenAmount(netRuneAmount);
        tokenFee = tokenAmount - netTokenAmount;

        // transfer the full amount of tokens, then burn the net amount. rest is kept as fees.
        token.safeTransferFrom(msg.sender, address(this), tokenAmount);
        token.burn(netTokenAmount);

        numTransfersTotal++;
        emit RuneTransferToBtc(
            numTransfersTotal,
            msg.sender,
            address(token),
            rune,
            tokenAmount,
            netRuneAmount,
            receiverBtcAddress,
            policy.flatFeeBaseCurrency,
            tokenFee
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

    function getEvmToBtcTransferPolicy(address token) public view returns (EvmToBtcTransferPolicy memory policy) {
        policy = evmToBtcTransferPoliciesByToken[token];
        if (policy.maxTokenAmount == 0) {
            policy = evmToBtcTransferPoliciesByToken[address(0)];
        }
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
    whenNotFrozen
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
        token.mintTo(to, tokenAmount);

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

    /// @dev Withdraw rBTC from the contract.
    /// Can only be called by admins.
    /// @param amount   The amount of rBTC to withdraw (in wei).
    /// @param receiver The address to send the rBTC to.
    function withdrawBaseCurrency(
        uint256 amount,
        address payable receiver
    )
    external
    onlyAdmin
    {
        // TODO: emit event
        receiver.sendValue(amount);
    }

    /// @dev A utility for withdrawing accumulated fees, and tokens accidentally sent to the contract.
    /// Can only be called by admins.
    /// @param token    The ERC20 token to withdraw.
    /// @param amount   The amount of the token to withdraw (in wei/base units).
    /// @param receiver The address to send the tokens to.
    function withdrawTokens(
        IERC20 token,
        uint256 amount,
        address receiver
    )
    external
    onlyAdmin
    {
        // TODO: emit event
        token.safeTransfer(receiver, amount);
    }

    /// @dev Transfer full balance of a Rune Token (probably collected as fees)
    ///      to a BTC address, without double-spending fees
    function transferTokenBalanceToBtc(
        RuneToken token,
        string calldata receiverBtcAddress
    )
    external
    onlyAdmin
    {
        uint256 tokenAmount = address(token).balance;
        require(tokenAmount > 0, "zero balance");

        uint256 rune = token.rune();
        require(isRuneRegistered(rune), "rune not registered");

        require(btcAddressValidator.isValidBtcAddress(receiverBtcAddress), "invalid BTC address");

        // do the double conversion to account for decimal differences
        uint256 runeAmount = token.getRuneAmount(tokenAmount);
        tokenAmount = token.getTokenAmount(runeAmount);
        require(tokenAmount > 0, "received token amount is zero");

        token.burn(tokenAmount);

        numTransfersTotal++;
        emit RuneTransferToBtc(
            numTransfersTotal,
            msg.sender,
            address(token),
            rune,
            tokenAmount,
            runeAmount,
            receiverBtcAddress,
            0,
            0
        );
    }

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

    function setEvmToBtcTransferPolicy(
        address token,
        uint256 maxTokenAmount,
        uint256 minTokenAmount,
        uint256 flatFeeBaseCurrency,
        uint256 flatFeeTokens,
        uint256 dynamicFeeTokens
    )
    external
    onlyAdmin
    {
        _setEvmToBtcTransferPolicy(
            token,
            maxTokenAmount,
            minTokenAmount,
            flatFeeBaseCurrency,
            flatFeeTokens,
            dynamicFeeTokens
        );
    }

    function _setEvmToBtcTransferPolicy(
        address token,
        uint256 maxTokenAmount,
        uint256 minTokenAmount,
        uint256 flatFeeBaseCurrency,
        uint256 flatFeeTokens,
        uint256 dynamicFeeTokens
    )
    internal
    {
        EvmToBtcTransferPolicy storage policy = evmToBtcTransferPoliciesByToken[token];
        policy.maxTokenAmount = maxTokenAmount;
        policy.minTokenAmount = minTokenAmount;
        policy.flatFeeBaseCurrency = flatFeeBaseCurrency;
        policy.flatFeeTokens = flatFeeTokens;
        policy.dynamicFeeTokens = dynamicFeeTokens;
        emit EvmToBtcTransferPolicyChanged(
            token,
            maxTokenAmount,
            minTokenAmount,
            flatFeeBaseCurrency,
            flatFeeTokens,
            dynamicFeeTokens
        );
    }

    // FREEZE / PAUSE API

    /// @dev Pause the contract, stopping new transfers.
    /// Can only be called by pausers.
    function pause() external onlyPauser {
        _pause();
    }

    /// @dev Freeze the contract, disabling the use of federator methods as well as pausing it.
    /// Can only be called by guards.
    /// @dev This is intended only for emergencies (such as in the event of a hostile federator network),
    /// as it effectively stops the system from functioning at all.
    function freeze() external onlyGuard {
        if (!paused()) { // we don't want to risk a revert
            _pause();
        }
        _freeze();
    }

    /// @dev Unpause the contract, allowing new transfers again. Cannot unpause when frozen.
    /// After unfreezing, the contract needs to be unpaused manually.
    /// Can only be called by pausers.
    function unpause() external onlyPauser whenNotFrozen {
        _unpause();
    }

    /// @dev Unfreeze the contract, re-enabling the use of federator methods.
    /// Unfreezing does not automatically unpause the contract.
    /// Can only be called by guards.
    function unfreeze() external onlyGuard {
        _unfreeze();
        //_unpause(); // it's best to have the option unpause separately
    }
}
