// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";


contract RuneToken is ERC20 {
    address public deployer;

    uint256 public rune;
    uint8 public runeDivisibility;
    uint8 private tokenDecimals;
    uint256 public runeAmountDivisor;

    modifier onlyDeployer() {
        require(msg.sender == deployer, "only deployer");
        _;
    }

    constructor(
        string memory _tokenName,
        string memory _tokenSymbol,
        uint256 _rune,
        uint8 _runeDivisibility
    ) ERC20(_tokenName, _tokenSymbol) {
        deployer = msg.sender;

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

     function decimals() public view override returns (uint8) {
         return tokenDecimals;
     }

    function getRuneAmount(
        uint256 tokenAmount
    )
    public
    view
    returns (uint256) {
        if (runeAmountDivisor == 1) {
            return tokenAmount;
        }
        require(
            tokenAmount % runeAmountDivisor == 0,
            "amount too precise"
        );
        return tokenAmount / runeAmountDivisor;
    }

    function getTokenAmount(
        uint256 runeAmount
    )
    public
    view
    returns (uint256) {
        return runeAmount * runeAmountDivisor;
    }

    // TODO: rename mintTo
    function mint(
        address to,
        uint256 amount
    )
    external
    onlyDeployer
    {
        _mint(to, amount);
    }

    // TODO: drop from argument and onlyDeployer
    function burn(
        address from,
        uint256 amount
    )
    external
    onlyDeployer
    {
        _burn(from, amount);
    }
}
