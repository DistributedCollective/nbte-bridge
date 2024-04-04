//SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

import "../shared/NBTEBridgeAccessControllable.sol";
import "../shared/IBTCAddressValidator.sol";

/// @title The contract that validates Bitcoin addresses.
/// @dev Supports both bech32 and non-bech32 addresses.
contract BTCAddressValidator is IBTCAddressValidator, NBTEBridgeAccessControllable {
    string public bech32Prefix;  // prefix incuding separator but without version
    bool supportsLegacy;
    string[] public nonBech32Prefixes;

    // The wiki gives these numbers as valid values for address length
    // (https://en.bitcoin.it/wiki/Invoice_address)
    uint256 public bech32MinLength = 42; // 44 for regtest
    uint256 public bech32MaxLength = 64; // 62 for others, 64 for regtest
    uint256 public nonBech32MinLength = 26;
    uint256 public nonBech32MaxLength = 35;
    uint8 public maxSegwitVersion = 1; // 0 = segwit v0 (p2wsh/p2wpkh), 1 = taproot, previous versions implicitly supported
    uint256 precomputedBech32ChecksumStart;

    uint8 constant BECH32_FIRST_ORD = 48;
    uint8 constant BECH32_LAST_ORD = 122;
    uint8 constant BECH32_MAX_VALID_MAPPED = 0x1f;
    bytes constant BECH32_ALPHABET_MAP = hex"0fff0a1115141a1e0705ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff1dff180d19090817ff12161f1b13ff010003100b1c0c0e060402";
    uint256 constant SEGWIT_V0_BECH32_CHECKSUM_CONSTANT = 1;  // bech32 original
    uint256 constant SEGWIT_V1_BECH32_CHECKSUM_CONSTANT = 0x2bc830a3;  // bech32m

    /// @dev The constructor.
    /// @param _accessControl       Address of the FastBTCAccessControl contract.
    /// @param _bech32Prefix        The prefix that bech32 addresses start with, including separattor but without
    ///                             version (e.g. "bc1"/"tb1"/"bcrt1"). Differs between mainnet/testnet/regtest.
    /// @param _nonBech32Prefixes   Valid prefixes for non-bech32 addresses. Differs between mainnet/testnet/regtest.
    constructor(
        address _accessControl,
        string memory _bech32Prefix,
        string[] memory _nonBech32Prefixes
    )
    NBTEBridgeAccessControllable(_accessControl)
    {
        _setBech32Prefix(_bech32Prefix);
        supportsLegacy = _nonBech32Prefixes.length > 0;
        nonBech32Prefixes = _nonBech32Prefixes;
    }

    /// @dev Is the given string is a valid Bitcoin address?
    /// @dev Additional off-chain validation is recommended
    /// @param _btcAddress  A (possibly invalid) Bitcoin address.
    /// @return The validity of the address, as boolean.
    function isValidBtcAddress(
        string calldata _btcAddress
    )
    external
    view
    override
    returns (bool)
    {
        if (startsWith(_btcAddress, bech32Prefix)) {
            return validateBech32Address(_btcAddress);
        } else if (supportsLegacy) {
            return validateNonBech32Address(_btcAddress);
        }
        else return false;
    }

    /// @dev Is the given address a valid bech32 Bitcoin address?
    function validateBech32Address(
        string calldata _btcAddress
    )
    private
    view
    returns (bool)
    {
        bytes memory _btcAddressBytes = bytes(_btcAddress);
        if (_btcAddressBytes.length < bech32MinLength || _btcAddressBytes.length > bech32MaxLength) {
            return false;
        }

        uint256 chk = precomputedBech32ChecksumStart;

        uint256 checksumConstant = SEGWIT_V0_BECH32_CHECKSUM_CONSTANT;
        unchecked {
            bytes1 versionUnmapped = _btcAddressBytes[bytes(bech32Prefix).length];
            if (uint8(versionUnmapped) < BECH32_FIRST_ORD) {
                return false;
            }
            uint8 version = uint8(BECH32_ALPHABET_MAP[uint8(versionUnmapped) - BECH32_FIRST_ORD]);
            if (version > maxSegwitVersion) {
                return false;
            }
            if (version >= 1) {
                checksumConstant = SEGWIT_V1_BECH32_CHECKSUM_CONSTANT;
            }

            // micro-optimization: compute polymod for version here
            chk = polymodStep(chk) ^ uint8(version);
        }

        unchecked {
            for (uint256 i = bytes(bech32Prefix).length + 1; i < _btcAddressBytes.length; i++) {
                bytes1 c = _btcAddressBytes[i];
                uint8 ord = uint8(c);
                if (ord < BECH32_FIRST_ORD || ord > BECH32_LAST_ORD) {
                    return false;
                }
                bytes1 mapped = BECH32_ALPHABET_MAP[ord - BECH32_FIRST_ORD];
                if (uint8(mapped) > BECH32_MAX_VALID_MAPPED) {
                    return false;
                }

                chk = polymodStep(chk) ^ uint8(mapped);
            }
        }

        if (chk != checksumConstant) {
            return false;
        }
        return true;
    }

    /// @dev Is the given address a valid non-bech32 Bitcoin address?
    function validateNonBech32Address(
        string calldata _btcAddress
    )
    private
    view
    returns (bool)
    {
        bytes memory _btcAddressBytes = bytes(_btcAddress);

        if (_btcAddressBytes.length < nonBech32MinLength || _btcAddressBytes.length > nonBech32MaxLength) {
            return false;
        }

        if (!hasValidNonBech32Prefix(_btcAddress)) {
            return false;
        }

        unchecked {
            for (uint i = 1; i < _btcAddressBytes.length; i++) {
                uint8 c = uint8(_btcAddressBytes[i]);
                bool isValidCharacter = (
                    (c >= 0x31 && c <= 0x39) // between "1" and "9" (0 is not valid)
                    ||
                    (c >= 0x41 && c <= 0x5a && c != 0x49 && c != 0x4f) // between "A" and "Z" but not "I" or "O"
                    ||
                    (c >= 0x61 && c <= 0x7a && c != 0x6c) // between "a" and "z" but not "l"
                );
                if (!isValidCharacter) {
                    return false;
                }
            }
        }

        return true;
    }

    /// @dev Does the given address start with a valid non-bech32 prefix?
    function hasValidNonBech32Prefix(
        string calldata _btcAddress
    )
    private
    view
    returns (bool) {
        unchecked {
            for (uint i = 0; i < nonBech32Prefixes.length; i++) {
                if (startsWith(_btcAddress, nonBech32Prefixes[i])) {
                    return true;
                }
            }
        }

        return false;
    }

    /// @dev Does a string start with a prefix?
    function startsWith(
        string calldata _string,
        string memory _prefix
    )
    private
    pure
    returns (bool) {
        bytes memory _stringBytes = bytes(_string);
        bytes memory _prefixBytes = bytes(_prefix);
        if (_prefixBytes.length > _stringBytes.length) {
            return false;
        }
        unchecked {
            for (uint i = 0; i < _prefixBytes.length; i++) {
                if (_stringBytes[i] != _prefixBytes[i]) {
                    return false;
                }
            }
        }
        return true;
    }

    function polymodStep(
        uint256 pre
    )
    private
    pure
    returns (uint256) {
        uint256 b = pre >> 25;

        pre = (pre & 0x1ffffff) << 5;
        if ((b >> 0) & 1 != 0) {
            pre ^= 0x3b6a57b2;
        }
        if ((b >> 1) & 1 != 0) {
            pre ^= 0x26508e6d;
        }
        if ((b >> 2) & 1 != 0) {
            pre ^= 0x1ea119fa;
        }
        if ((b >> 3) & 1 != 0) {
            pre ^= 0x3d4233dd;
        }
        if ((b >> 4) & 1 != 0) {
            pre ^= 0x2a1462b3;
        }
        return pre;
    }

    // ADMIN API

    /// @dev Sets the valid prefix for bech32 addresses. Can only be called by admins.
    /// @param _prefix  The new bech32 address prefix.
    function setBech32Prefix(
        string memory _prefix
    )
    external
    onlyAdmin
    {
        _setBech32Prefix(_prefix);
    }

    function _setBech32Prefix(
        string memory _prefix
    )
    internal
    {
        require(bech32MinLength > bytes(_prefix).length + 1, "minLength must be greater than prefix length plus version");
        bech32Prefix = _prefix;

        // precompute bech32 checksum start
        uint256 chk = 1;
        uint256 i = 0;
        for (; i < bytes(bech32Prefix).length - 1; i++) {
            bytes1 c = bytes(bech32Prefix)[i];
            chk = polymodStep(chk) ^ (uint8(c) >> 5);
        }
        chk = polymodStep(chk);
        for (uint256 j = 0; j < i; j++) {
            chk = polymodStep(chk) ^ (uint8(bytes(bech32Prefix)[j]) & 0x1f);
        }
        require(uint8(bytes(bech32Prefix)[i]) == 0x31, "bech32Prefix doesn't end in '1'");
        precomputedBech32ChecksumStart = chk;
    }

    /// @dev Sets the valid prefix for non-bech32 addresses. Can only be called by admins.
    /// @param _prefixes    An array of the new valid non-bech32 prefixes.
    function setNonBech32Prefixes(
        string[] memory _prefixes
    )
    external
    onlyAdmin
    {
        nonBech32Prefixes = _prefixes;
        supportsLegacy = nonBech32Prefixes.length > 0;
    }

    /// @dev Set the minimum and maximum lengths of acceptable bech32 addresses. Can only be called by admins.
    /// @param _minLength   The new minimum length.
    /// @param _maxLength   The new maximum length.
    function setBech32MinAndMaxLengths(
        uint256 _minLength,
        uint256 _maxLength
    )
    external
    onlyAdmin
    {
        require(_minLength <= _maxLength, "minLength greater than maxLength");
        require(_minLength > bytes(bech32Prefix).length + 1, "minLength must be greater than prefix length plus version");
        bech32MinLength = _minLength;
        bech32MaxLength = _maxLength;
    }

    /// @dev Set the minimum and maximum lengths of acceptable non-bech32 addresses. Can only be called by admins.
    /// @param _minLength   The new minimum length.
    /// @param _maxLength   The new maximum length.
    function setNonBech32MinAndMaxLengths(
        uint256 _minLength,
        uint256 _maxLength
    )
    external
    onlyAdmin
    {
        require(_minLength <= _maxLength, "minLength greater than maxLength");
        nonBech32MinLength = _minLength;
        nonBech32MaxLength = _maxLength;
    }

    /// @dev Set the maximum supported bech32/segwit version
    /// @param _version The new maximum version length.
    function setMaxSegwitVersion(
        uint8 _version
    )
    external
    onlyAdmin
    {
        maxSegwitVersion = _version;
    }
}
