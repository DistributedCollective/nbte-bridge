// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";


contract RuneToken is ERC20 {
    address public minter;

    uint256 public rune;
    uint8 public runeDivisibility;
    uint8 private tokenDecimals;
    uint256 public runeAmountDivisor;

    event Mint(address indexed to, uint256 amount);
    event Burn(address indexed from, uint256 amount);
    event MinterChanged(address indexed oldMinter, address indexed newMinter);

    modifier onlyMinter() {
        require(msg.sender == minter, "only minter");
        _;
    }

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
        // TODO: might want to re-enable this validation
//        require(
//            tokenAmount % runeAmountDivisor == 0,
//            "amount too precise"
//        );
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

    function changeMinter(
        address newMinter
    )
    external
    onlyMinter
    {
        minter = newMinter;
        emit MinterChanged(msg.sender, newMinter);
    }

    function burn(
        uint256 amount
    )
    external
    {
        _burn(msg.sender, amount);
        emit Burn(msg.sender, amount);
    }
}
