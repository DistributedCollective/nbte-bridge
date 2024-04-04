// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";


contract RuneSideToken is ERC20 {
    address public deployer;

    modifier onlyDeployer() {
        require(msg.sender == deployer, "only deployer");
        _;
    }

    constructor(string memory name, string memory symbol) ERC20(name, symbol) {
        deployer = msg.sender;
    }

    // TODO: decimals from runes, or always 18 decimals?
    // function decimals() public pure override returns (uint8) {
    //     return 18;
    // }

    function mint(
        address to,
        uint256 amount
    )
    external
    onlyDeployer
    {
        _mint(to, amount);
    }

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
