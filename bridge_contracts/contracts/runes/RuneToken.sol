// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";


/// @title A token deployed for bridged Runes
contract RuneToken is ERC20 {
    /// @dev the address that's allowed to mint new tokens
    address public minter;

    /// @dev The base26-encoded Rune that corresponds to this token
    uint256 public rune;

    /// @dev the decimal places of the rune
    uint8 public runeDivisibility;

    /// @dev the decimal places of the token
    uint8 private tokenDecimals;

    /// @dev the divisor to convert between rune and token amounts, pre-calculated for gas savings
    uint256 public  runeAmountDivisor;

    /// @dev emitted when new tokens are minted
    event Mint(address indexed to, uint256 amount);

    /// @dev emitted when tokens are burned
    event Burn(address indexed from, uint256 amount);

    /// @dev emitted when the minter is changed
    event MinterChanged(address indexed oldMinter, address indexed newMinter);

    /// @dev Validate that a function can only be called by the minter
    modifier onlyMinter() {
        require(msg.sender == minter, "only callable by minter");
        _;
    }

    /// @dev Constructor
    /// @param _tokenName   The name of the token. Normally Rune name, but can be overridden
    /// @param _tokenSymbol The symbol of the token. Normally Rune symbol, but can be overridden
    /// @param _rune        The base26-encoded Rune that corresponds to this token
    /// @param _runeDivisibility The decimal places of the rune
    constructor(
        string memory _tokenName,
        string memory _tokenSymbol,
        uint256 _rune,
        uint8 _runeDivisibility
    ) ERC20(_tokenName, _tokenSymbol) {
        minter = msg.sender;

        rune = _rune;
        runeDivisibility = _runeDivisibility;

        if (_runeDivisibility < 18) {
            tokenDecimals = 18;
            runeAmountDivisor = 10 ** (18 - _runeDivisibility);
        } else {
            tokenDecimals = _runeDivisibility;
            runeAmountDivisor = 1;
        }
    }

    /// @dev Returns the decimals of the token
     function decimals() public view override returns (uint8) {
         return tokenDecimals;
     }

    /// @dev Convert amount in Rune Tokens to amount in Runes (as the token and rune might have different decimals)
    /// @dev Doesn't validate that there's no remainder
    function getRuneAmount(
        uint256 tokenAmount
    )
    public
    view
    returns (uint256) {
        // Note: this validation is disabled. We have getRuneAmountAndRemainder for outside validation.
        // require(
        //     tokenAmount % runeAmountDivisor == 0,
        //     "amount too precise"
        // );
        return tokenAmount / runeAmountDivisor;
    }

    /// @dev Convert amount in Rune Tokens to amount in Runes and returns the possible remainder
    function getRuneAmountAndRemainder(
        uint256 tokenAmount
    )
    public
    view
    returns (uint256, uint256) {
        return (tokenAmount / runeAmountDivisor, tokenAmount % runeAmountDivisor);
    }

    /// @dev Convert amount in Runes to amount in Rune Tokens.
    /// @dev The rune tokens always have at least the same number of decimals as the rune, so no remainder is possible
    function getTokenAmount(
        uint256 runeAmount
    )
    public
    view
    returns (uint256) {
        return runeAmount * runeAmountDivisor;
    }

    /// @dev Mint new tokens. Only callable by the minter
    /// @param to     The address to mint the tokens to
    /// @param amount The amount of tokens to mint
    function mintTo(
        address to,
        uint256 amount
    )
    external
    onlyMinter
    {
        _mint(to, amount);
        emit Mint(to, amount);
    }

    /// @dev Burn tokens from the sender
    function burn(
        uint256 amount
    )
    external
    {
        _burn(msg.sender, amount);
        emit Burn(msg.sender, amount);
    }

    /// @dev Change the minter. Only callable by the current minter.
    function changeMinter(
        address newMinter
    )
    external
    onlyMinter
    {
        minter = newMinter;
        emit MinterChanged(msg.sender, newMinter);
    }

}
