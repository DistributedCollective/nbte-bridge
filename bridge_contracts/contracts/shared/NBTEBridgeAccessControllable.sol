//SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

import "./INBTEBridgeAccessControl.sol";

/// @title An utility mixin to inherit contracts that require access control from.
abstract contract NBTEBridgeAccessControllable {
    /// @dev The NBTEBridgeAccessControl address.
    INBTEBridgeAccessControl public accessControl;

    /// @dev The constructor.
    /// @param _accessControl   The NBTEBridgeAccessControl address.
    constructor(
        address _accessControl
    )
    {
        accessControl = INBTEBridgeAccessControl(_accessControl);
    }

    /// @dev A modifier that ensures only a federator can call a function.
    modifier onlyFederator() {
        accessControl.checkFederator(msg.sender);
        _;
    }

    /// @dev A modifier that ensures only an admin can call a function.
    modifier onlyAdmin() {
        accessControl.checkAdmin(msg.sender);
        _;
    }

    /// @dev A modifier that ensures only a pauser can call a function.
    modifier onlyPauser() {
        accessControl.checkPauser(msg.sender);
        _;
    }

    /// @dev A modifier that ensures only a guard can call a function.
    modifier onlyGuard() {
        accessControl.checkGuard(msg.sender);
        _;
    }

    /// @dev A modifier that ensures only a configuration admin can call a function.
    modifier onlyConfigAdmin() {
        accessControl.checkConfigAdmin(msg.sender);
        _;
    }
}
