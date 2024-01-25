// SPDX-License-Identifier: MIT
pragma solidity ^0.8.9;

/// @dev Interface for a contract that's allowed to mint base currency
/// @dev This would be implemented pre-compiled contract developed by the team behind the rollup chain
interface IPrecompiledMintingContract {
    event Minted(address indexed to, uint256 amount);

    /// @dev mint base currency to address
    function mint(address payable to, uint256 amount) external;
}
