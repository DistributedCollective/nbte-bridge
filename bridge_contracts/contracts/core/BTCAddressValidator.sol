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
    uint256 precomputedBech32ChecksumStart; // pre-computed checksum start for bech32 addresses, for gas savings

    // @dev Map each uint8 to it's bech32 value. Generated using generate_bech32_alphabet_map.py
    // @dev Values are 0xff for invalid characters, 0x00-0x1f for valid characters
    bytes constant BECH32_ALPHABET_MAP = hex"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0fff0a1115141a1e0705ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff1dff180d19090817ff12161f1b13ff010003100b1c0c0e060402ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff";
    uint256 constant SEGWIT_V0_BECH32_CHECKSUM_CONSTANT = 1;  // bech32 (segwit v0)
    uint256 constant SEGWIT_V1_BECH32_CHECKSUM_CONSTANT = 0x2bc830a3;  // bech32m (segwit v1+)

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
    {
        _setAccessControl(_accessControl);
        _setBech32Prefix(_bech32Prefix);
        supportsLegacy = _nonBech32Prefixes.length > 0;
        nonBech32Prefixes = _nonBech32Prefixes;
    }

    /// @dev Is the given string is a valid Bitcoin address?
    /// @dev Additional off-chain validation is recommended -- this doesn't check everything, especially for non-bech32.
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
    /// @dev This also validates the checksum and version.
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

        // Read the alphabet here once to avoid repeated storage read. Saves around ~4000 gas for a P2WSH address.
        bytes memory bech32AlphabetMap = BECH32_ALPHABET_MAP;

        uint256 chk = precomputedBech32ChecksumStart;

        uint256 checksumConstant = SEGWIT_V0_BECH32_CHECKSUM_CONSTANT;
        unchecked {
            bytes1 versionUnmapped = _btcAddressBytes[bytes(bech32Prefix).length];
            uint8 version = uint8(bech32AlphabetMap[uint8(versionUnmapped)]);
            if (version > maxSegwitVersion) {
                // no need to check version > 0x1f here, maxSegwitVersion must 0x1f or less
                return false;
            }
            if (version >= 1) {
                checksumConstant = SEGWIT_V1_BECH32_CHECKSUM_CONSTANT;
            }

            // micro-optimization: compute polymod for version here
            chk = polymodStep(chk) ^ version;
        }

        unchecked {
            for (uint256 i = bytes(bech32Prefix).length + 1; i < _btcAddressBytes.length; i++) {
                uint8 mapped = uint8(bech32AlphabetMap[uint8(_btcAddressBytes[i])]);
                if (mapped > 0x1f) {
                    // not a valid bech32 character
                    // checking == 0xff would save a bit of gas but this is safer
                    return false;
                }

                chk = polymodStep(chk) ^ mapped;
            }
        }

        if (chk != checksumConstant) {
            return false;
        }
        return true;
    }

    /// @dev Is the given address a valid non-bech32 Bitcoin address?
    /// @dev This only checks the address length, prefix and allowed characters. Off-chain validation is recommended!
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
        // This is implemented in assembly for gas savings (saves around 3000 gas during the execution of
        // validateBech32Address for a P2WSH address)
        // Non-assembly version commented out below.
        // uint256 b = pre >> 25;
        // pre = (pre & 0x1ffffff) << 5;
        // if ((b >> 0) & 1 != 0) {
        //     pre ^= 0x3b6a57b2;
        // }
        // if ((b >> 1) & 1 != 0) {
        //     pre ^= 0x26508e6d;
        // }
        // if ((b >> 2) & 1 != 0) {
        //     pre ^= 0x1ea119fa;
        // }
        // if ((b >> 3) & 1 != 0) {
        //     pre ^= 0x3d4233dd;
        // }
        // if ((b >> 4) & 1 != 0) {
        //     pre ^= 0x2a1462b3;
        // }
        assembly {
            let b := shr(25, pre)
            pre := shl(5, and(pre, 0x1ffffff))
            if and(b, 0x01) {
                pre := xor(pre, 0x3b6a57b2)
            }
            if and(b, 0x02) {
                pre := xor(pre, 0x26508e6d)
            }
            if and(b, 0x04) {
                pre := xor(pre, 0x1ea119fa)
            }
            if and(b, 0x08) {
                pre := xor(pre, 0x3d4233dd)
            }
            if and(b, 0x10) {
                pre := xor(pre, 0x2a1462b3)
            }
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
        require(_version <= 0x1f, "version must be less than 0x1f to fit in bech32 alphabet");
        maxSegwitVersion = _version;
    }
}
