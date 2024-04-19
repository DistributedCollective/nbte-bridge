// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

import {NBTEBridgeAccessControllable} from "../shared/NBTEBridgeAccessControllable.sol";
import {IBTCAddressValidator} from "../shared/IBTCAddressValidator.sol";
import {INBTEBridgeAccessControl} from "../shared/INBTEBridgeAccessControl.sol";
import {Freezable} from "../shared/Freezable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/security/PausableUpgradeable.sol";
import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Address} from "@openzeppelin/contracts/utils/Address.sol";
import {RuneToken} from "./RuneToken.sol";


/// @title The main Rune Bridge contract
/// @notice Allows the federator network to mint new Rune Tokens based on rune deposits, and accepts the Rune Tokens
//          back, which will burn them and instruct the federator network to release Runes.
contract RuneBridge is Initializable, NBTEBridgeAccessControllable, Freezable, PausableUpgradeable {
    using SafeERC20 for IERC20;
    using SafeERC20 for RuneToken;
    using Address for address payable;

    /// @dev Fees and max/min amounts when transferring Rune Tokens from EVM to BTC
    struct EvmToBtcTransferPolicy {
        uint256 maxTokenAmount;         // if this is zero, the transfer policy is treated as unset
        uint256 minTokenAmount;
        uint256 flatFeeBaseCurrency;
        uint256 flatFeeTokens;
        uint256 dynamicFeeTokens;       // base unit is 0.01 %
    }

    /// @dev Emitted when a transfer from EVM to BTC is initiated.
    event RuneTransferToBtc(
        uint256 counter,                // an 1-based counter shared between both types of transfer
        address indexed from,           // the user
        address indexed token,          // the Rune Token the user sent
        uint256 indexed rune,           // the base26-encoded rune
        uint256 transferredTokenAmount, // the total amount of tokens sent by the user
        uint256 netRuneAmount,          // the amount of runes the receiver will receive
        string receiverBtcAddress,      // the BTC address of the receiver
        uint256 baseCurrencyFee,        // the amount of base currency paid as fees
        uint256 tokenFee                // the amount of tokens kept as fees
    );

    /// @dev Emitted when a transfer from BTC to EVM is accepted by the federation network
    event RuneTransferFromBtc(
        uint256 counter,                // an 1-based counter shared between both types of transfer
        address indexed to,             // the user
        address indexed token,          // the Rune Token the user received
        uint256 indexed rune,           // the base26-encoded Rune
        //uint256 transferredRuneAmount,  // the total amount of Runes sent by the user
        uint256 netTokenAmount,         // the amount of tokens the receiver received
        bytes32 btcTxId,                // the bitcoin tx hash of the transaction from the user
        uint256 btcTxVout               // the vout index of the transaction from the user
    );

    /// @dev Emitted when a new Rune is registered on the bridge and a new Rune Token is deployed
    event RuneRegistered(
        uint256 counter,                // an 1-based counter shared between both types of transfer
        uint256 rune,                   // the base26-encoded Rune
        address token                   // the freshly deployed Rune Token
    );

    /// @dev Emitted when a user requests the registration of a new Rune
    event RuneRegistrationRequested(
        uint256 rune,                   // the base26-encoded Rune
        address requester,              // the user who requested the registration
        uint256 baseCurrencyFee         // the amount of base currency paid as fees
    );

    /// @dev Emitted when Rune registration requests are enabled or disabled
    event RuneRegistrationRequestsEnabled(
        bool enabled
    );

    /// @dev Emitted when the base currency fee for registering a new Rune is changed
    event RuneRegistrationFeeChanged(
        uint256 baseCurrencyFee
    );

    /// @dev Emitted when an admin withdraws funds (fees or accidentally sent tokens) from the contract
    event AdminWithdrawal(
        address indexed token,          // address(0) indicates withdrawal of the base currency
        uint256 amount
    );

    /// @dev emitted when the access control contract is changed
    event AccessControlChanged(
        address oldAccessControl,
        address newAccessControl
    );

    /// @dev emitted when the BTC address validator is changed
    event BTCAddressValidatorChanged(
        address oldAccessControl,
        address newAccessControl
    );

    /// @dev emitted when the EVM to BTC transfer policy is changed
    event EvmToBtcTransferPolicyChanged(
        address indexed token,          // 0x0 for default policy
        uint256 maxTokenAmount,
        uint256 minTokenAmount,
        uint256 flatFeeBaseCurrency,
        uint256 flatFeeTokens,
        uint256 dynamicFeeTokens
    );

    /// @dev Denominator for the dynamic fee. uint16; 0.01 % granularity
    uint256 public constant DYNAMIC_FEE_DIVISOR = 10_000;

    /// @dev The contract used to validate receiving BTC addresses
    IBTCAddressValidator public btcAddressValidator;

    /// @dev total number of transfers, both sides. used as a counter for the events
    uint256 public numTransfersTotal;

    /// @dev Mapping rune => token address. Values 0x0 mean that the rune is not registered
    mapping(uint256 => address) public tokensByRune;

    /// @dev Mapping token address => rune. Values 0 mean that the token is not registered
    mapping(address => uint256) public runesByToken;

    /// @dev deployed rune tokens
    address[] public runeTokens;

    /// @dev Can users currently request the registration of new Runes?
    bool public runeRegistrationRequestsEnabled;

    /// @dev The base currency fee for registering a new Rune
    uint256 public runeRegistrationFee;

    /// @dev Mapping rune => registration requested
    mapping(uint256 => bool) public runeRegistrationRequested;

    /// @dev Mapping txHash => vout => rune => processed?
    mapping(bytes32 => mapping(uint256 => mapping(uint256 => bool))) processedTransfersFromBtc;

    /// @dev EVM to BTC transfer policies by token. Index 0x0 is the default policy
    mapping(address => EvmToBtcTransferPolicy) public evmToBtcTransferPoliciesByToken;

    // @dev storage gap for upgradeability
    uint256[50] private __gap;

    /// @dev Checks that the Rune registration requests are enabled
    modifier whenRuneRegistrationRequestsEnabled() {
        require(runeRegistrationRequestsEnabled, "rune registration requests disabled");
        _;
    }

    /// @dev The initializer
    /// @param _accessControl       Address of the NBTEBridgeBTCAccessControl contract.
    /// @param _btcAddressValidator Address of the BTCAddressValidator contract.
    function initialize(
        address _accessControl,
        address _btcAddressValidator
    )
    public
    initializer
    {
        _setAccessControl(_accessControl);
        btcAddressValidator = IBTCAddressValidator(_btcAddressValidator);

        // set default transfer policy and rune registration fee

        runeRegistrationFee = 0.0016 ether;

        _setEvmToBtcTransferPolicy(
            address(0),
            1_000_000 ether,
            1,
            0.0003 ether, // 30k sat
            0,
            40  // 0.4%
        );
    }

    // PUBLIC USER API
    // ===============

    /// @dev Accepts Rune Tokens from users and instructs the network to release runes based on that
    /// @param token                The Rune Token to accept. Must be a token deployed by the bridge.
    /// @param tokenAmount          The amount of tokens to accept
    /// @param receiverBtcAddress   The BTC address to send the runes to.
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

        uint256 rune = getRuneByToken(address(token)); // this validates that it has been registered
        require(rune == token.rune(), "rune mismatch"); // double validation for the paranoid

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

        // it's very important we don't emit an event with zero amount, zero amounts in Runestone Edicts have
        // special case behaviour
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

    /// @dev Request the registration of a new Rune on the bridge
    /// @param rune The base26-encoded rune
    function requestRuneRegistration(
        uint256 rune
    )
    public
    payable
    whenRuneRegistrationRequestsEnabled
    whenNotPaused
    {
        require(!isRuneRegistered(rune), "rune already registered");
        require(!runeRegistrationRequested[rune], "registration already requested");
        require(msg.value == runeRegistrationFee, "incorrect base currency fee");

        runeRegistrationRequested[rune] = true;
        emit RuneRegistrationRequested(
            rune,
            msg.sender,
            msg.value
        );
    }

    /// @dev Is the Rune registered on the Bridge_
    function isRuneRegistered(uint256 rune) public view returns (bool) {
        return tokensByRune[rune] != address(0);
    }

    /// @dev Is the token a Rune Token deployed by the Bridge_
    function isTokenRegistered(address token) public view returns (bool) {
        return runesByToken[token] != 0;
    }

    /// @dev Number of Runes registered on the bridge
    function numRunesRegistered() public view returns (uint256) {
        return runeTokens.length;
    }

    /// @dev Get the Rune Token that corresponds to a rune. Validates that the rune is registered
    function getTokenByRune(uint256 rune) public view returns (address token) {
        token = tokensByRune[rune];
        require(token != address(0), "rune not registered");
    }

    /// @dev Get the Rune that corresponds to a Rune Token. Validates that the token is registered
    function getRuneByToken(address token) public view returns (uint256 rune) {
        rune = runesByToken[token];
        require(rune != 0, "token not registered");
    }

    /// @dev List all Rune Tokens deployed by the bridge
    function listTokens() public view returns (address[] memory) {
        return runeTokens;
    }

    /// @dev Get `count` Rune Tokens deployed by the bridge,  starting from `start`
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

    /// @dev Get the transfer policy when transferring Rune Tokens to BTC
    function getEvmToBtcTransferPolicy(address token) public view returns (EvmToBtcTransferPolicy memory policy) {
        policy = evmToBtcTransferPoliciesByToken[token];
        if (policy.maxTokenAmount == 0) {
            policy = evmToBtcTransferPoliciesByToken[address(0)];
        }
    }

    /// @dev Is the transfer, uniquely identified by txhash, vout, rune, already processed?
    function isTransferFromBtcProcessed(bytes32 txHash, uint256 vout, uint256 rune) public view returns (bool) {
        return processedTransfersFromBtc[txHash][vout][rune];
    }

    /// @dev Is the BTC address valid?
    function isValidBtcAddress(string calldata btcAddress) public view returns (bool) {
        return btcAddressValidator.isValidBtcAddress(btcAddress);
    }

    // FEDERATOR API
    // =============

    /// @dev Accepts a transfer by the federator network, mints the corresponding Rune Tokens
    /// @param to           The user to mint the tokens to
    /// @param rune         The base26-encoded rune
    /// @param runeAmount   The amount of runes to mint
    /// @param btcTxId      The rune transfer Bitcoin transaction hash
    /// @param btcTxVout    The rune transfer Bitcoin transaction output index
    /// @param signatures   The signatures of the federators
    function acceptTransferFromBtc(
        address to,
        uint256 rune,
        uint256 runeAmount,
        bytes32 btcTxId,
        uint256 btcTxVout,
        bytes[] memory signatures
    )
    external
    onlyFederator
    whenNotFrozen
    {
        // validate signatures
        bytes32 messageHash = getAcceptTransferFromBtcMessageHash(
            to,
            rune,
            runeAmount,
            btcTxId,
            btcTxVout
        );
        accessControl.checkFederatorSignatures(
            messageHash,
            signatures
        );

        RuneToken token = RuneToken(getTokenByRune(rune));  // this validates that it has been registered

        require(!isTransferFromBtcProcessed(btcTxId, btcTxVout, rune), "transfer already processed");
        _setTransferFromBtcProcessed(btcTxId, btcTxVout, rune);

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

    /// @dev Accepts a Rune registration request by the federation network, registers the Rune and deploys Rune token
    /// @param name              The name of the new Rune Token (normally Rune name, but can be overridden)
    /// @param symbol            The symbol of the new Rune Token (normally Rune symbol, but can be overridden)
    /// @param rune              The base26-encoded rune
    /// @param runeDivisibility  The divisibility (number of decimal places) of the Rune
    /// @param signatures   The signatures of the federators
    function acceptRuneRegistrationRequest(
        string memory name,
        string memory symbol,
        uint256 rune,
        uint8 runeDivisibility,
        bytes[] memory signatures
    )
    external
    onlyFederator
    whenNotFrozen
    {
        require(runeRegistrationRequested[rune], "registration not requested");

        // validate signatures
        bytes32 messageHash = getAcceptRuneRegistrationRequestMessageHash(
            name,
            symbol,
            rune,
            runeDivisibility
        );
        accessControl.checkFederatorSignatures(
            messageHash,
            signatures
        );

        // this validates that the rune is not already registered
        _registerRune(
            name,
            symbol,
            rune,
            runeDivisibility
        );
    }

    /// @dev Get the message hash for accepting a transfer from the federator network
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

    /// @dev Get the message hash for accepting a Rune registration request from the federator network
    function getAcceptRuneRegistrationRequestMessageHash(
        string memory name,
        string memory symbol,
        uint256 rune,
        uint8 runeDivisibility
    )
    public
    view
    returns (bytes32)
    {
        return keccak256(abi.encodePacked(
            "acceptRuneRegistrationRequest:",
            address(this),
            ":",
            name,
            ":",
            symbol,
            ":",
            rune,
            ":",
            runeDivisibility
        ));
    }

    /// @dev Get the number of required federators for a transfer
    function numRequiredFederators() public view returns (uint256) {
        return accessControl.numRequiredFederators();
    }

    /// @dev Is the given address a federator?
    function isFederator(address addressToCheck) external view returns (bool) {
        return accessControl.isFederator(addressToCheck);
    }

    function _setTransferFromBtcProcessed(
        bytes32 txHash,
        uint256 vout,
        uint256 rune
    )
    internal
    {
        // no validation here, calling functions will check it anyway before calling;
        processedTransfersFromBtc[txHash][vout][rune] = true;
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
        require(receiver != address(0), "Cannot withdraw to zero address");
        receiver.sendValue(amount);
        emit AdminWithdrawal(address(0), amount);
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
        require(receiver != address(0), "Cannot withdraw to zero address");
        token.safeTransfer(receiver, amount);
        emit AdminWithdrawal(address(token), amount);
    }

    /// @dev Register a new Rune on the bridge and deploy a new Rune Token
    /// @dev Can only be called by admins.
    /// @param name              The name of the new Rune Token (normally Rune name, but can be overridden)
    /// @param symbol            The symbol of the new Rune Token (normally Rune symbol, but can be overridden)
    /// @param rune              The base26-encoded rune
    /// @param runeDivisibility  The divisibility (number of decimal places) of the Rune
    function registerRune(
        string memory name,
        string memory symbol,
        uint256 rune,
        uint8 runeDivisibility
    )
    external
    onlyAdmin
    {
        _registerRune(
            name,
            symbol,
            rune,
            runeDivisibility
        );
    }

    /// @dev internal helper for registering a new Rune
    /// @param name              The name of the new Rune Token (normally Rune name, but can be overridden)
    /// @param symbol            The symbol of the new Rune Token (normally Rune symbol, but can be overridden)
    /// @param rune              The base26-encoded rune
    /// @param runeDivisibility  The divisibility (number of decimal places) of the Rune
    function _registerRune(
        string memory name,
        string memory symbol,
        uint256 rune,
        uint8 runeDivisibility
    )
    internal
    {
        require(!isRuneRegistered(rune), "rune already registered");
        _validateRune(rune);
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

    /// @dev Validate the rune number
    function _validateRune(
        uint256 rune
    )
    internal
    pure
    {
        require(rune <= type(uint128).max, "rune number too large");
        require(rune != 0, "rune cannot be zero");
    }

    /// @dev Set the EVM to BTC transfer policy for a Rune Token
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
        require(maxTokenAmount >= minTokenAmount, "max amount must be greater or equal than min amount");
        require(dynamicFeeTokens < DYNAMIC_FEE_DIVISOR, "dynamic fee must be less than 100%");
        // maxTokenAmount = 0 disables the policy
        require(maxTokenAmount == 0 || flatFeeTokens <= maxTokenAmount, "flat fee must be less than max amount");
        require(token == address(0) || isRuneRegistered(runesByToken[token]), "token not registered");

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

    /// @dev Enable or disable Rune registration requests
    function setRuneRegistrationRequestsEnabled(
        bool enabled
    )
    external
    onlyAdmin
    {
        runeRegistrationRequestsEnabled = enabled;
        emit RuneRegistrationRequestsEnabled(enabled);
    }

    /// @dev Update the base currency fee for rune registration requests
    function setRuneRegistrationFee(
        uint256 fee
    )
    external
    onlyAdmin
    {
        runeRegistrationFee = fee;
        emit RuneRegistrationFeeChanged(fee);
    }

    /// @dev Updates the Bitcoin address validator used.
    /// Can only be called by admins.
    /// @param newBtcAddressValidator   Address of the new BTCAddressValidator.
    function setBtcAddressValidator(
        IBTCAddressValidator newBtcAddressValidator
    )
    external
    onlyAdmin
    {
        require(address(newBtcAddressValidator) != address(0), "Cannot set to zero address");
        emit BTCAddressValidatorChanged(address(btcAddressValidator), address(newBtcAddressValidator));
        btcAddressValidator = newBtcAddressValidator;
    }

    /// @dev Updates the Access control. Can only be called by admins.
    ///      Note that there is normally no need to do this, but we have it here for upgradeability
    /// @param newAccessControl   Address of the new NBTEBridgeAccessControl.
    function setAccessControl(
        INBTEBridgeAccessControl newAccessControl
    )
    external
    onlyAdmin
    {
        require(address(newAccessControl) != address(0), "Cannot set to zero address");
        emit AccessControlChanged(address(accessControl), address(newAccessControl));
        _setAccessControl(address(newAccessControl));
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
