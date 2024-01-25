// SPDX-License-Identifier: MIT
pragma solidity ^0.8.9;

import "@openzeppelin/contracts/utils/Address.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "./IPrecompiledMintingContract.sol";

/// @title Mock contract for minting
/// @dev This is a mock contract for testing -- the real implementation would be a precompiled contract
/// done by the rollup dev team
contract PrecompiledMintingContractMock is IPrecompiledMintingContract, Ownable {
    using Address for address payable;

    event Funded(address indexed by, uint256 amount);

    address public minter;

    constructor(
        address _minter
    ) {
        minter = _minter;
    }

    modifier onlyMinter() {
        require(msg.sender == minter, "only minter");
        _;
    }

    function mint(
        address payable to,
        uint256 amount
    )
    external
    onlyMinter
    {
        to.sendValue(amount);
        emit Minted(to, amount);
    }

    function fund()
    external
    payable
    onlyOwner
    {
        emit Funded(msg.sender, msg.value);
    }

    function setMinter(
        address _minter
    )
    external
    onlyOwner
    {
        minter = _minter;
    }
}
