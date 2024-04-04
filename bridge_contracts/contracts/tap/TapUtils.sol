// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

contract TapUtils {
    // ******************************
    // * TAP address utils          *
    // ******************************

    uint256 constant BECH32M_CHECKSUM_CONSTANT = 0x2bc830a3;
    string public tapAddressPrefix;

    constructor(string memory _tapAddressPrefix) {
        tapAddressPrefix = _tapAddressPrefix;
    }

    // https://github.com/lightninglabs/taproot-assets/blob/main/address/records.go
    struct TapAddress {
        //"chain_params_hrp": "taprt",
        string chainParamsHrp;
        //"address_version": 0,
        uint8 addressVersion; // can be smaller than uint256
        //"asset_version": 0,
        uint8 assetVersion; // can be smaller than uint256
        //"asset_id": "7a3811630bb33503c6536c3a223d3caecb93fe55f4b3439528edf27b10d38e93",
        bytes32 assetId;
        //"group_key": "",
        bytes groupKey;
        //"script_key": "02a0afeb165f0ec36880b68e0baabd9ad9c62fd1a69aa998bc30e9a346202e078f",
        bytes scriptKey;
        //"internal_key": "02a0afeb165f0ec36880b68e0baabd9ad9c62fd1a69aa998bc30e9a346202e078f",
        bytes internalKey;
        //"tapscript_sibling": "",
        bytes tapscriptSibling;
        //"amount": 5577006791947779410
        uint64 amount; // can be smaller than uint256
        bytes assetType;
    }

    function decodeTapAddress(
        string calldata tapAddress
    ) public view returns (TapAddress memory ret) {
        bytes memory words = decodeBech32Address(
            tapAddressPrefix,
            tapAddress,
            BECH32M_CHECKSUM_CONSTANT
        );
        ret.chainParamsHrp = tapAddressPrefix;

        // read address using TLV encoding
        uint256 offset = 0;
        uint256 type_;
        uint256 length;
        int256 prevType = -1;
        while (offset < words.length) {
            (type_, offset) = readBigSize(
                words,
                offset
            );
            if (int256(type_) <= prevType) {
                revert("invalid TLV type order");
            }
            prevType = int256(type_);

            (length, offset) = readBigSize(
                words,
                offset
            );

            //console.log("TLV type: %s, length: %s", type_, length);

            if (type_ == 10) {
                // amt, for some reason encoded as BigSize
                uint64 amt;
                uint256 prevOffset = offset;
                (amt, offset) = readBigSize(
                    words,
                    offset
                );
                require(offset - prevOffset == length, "invalid length for amount");
                ret.amount = amt;
            } else if (type_ == 4) {
                require(length == 32, "invalid length for assetId");
                (ret.assetId, offset) = readBytes32(
                    words,
                    offset
                );
            } else {
                bytes memory data;
                (data, offset) = readBytes(
                    words,
                    offset,
                    length
                );
                if (type_ == 0) {
                    require(data.length == 1, "invalid length for address version");
                    ret.addressVersion = uint8(data[0]);
                } else if (type_ == 2) {
                    require(data.length == 1, "invalid length for asset version");
                    ret.assetVersion = uint8(data[0]);
                    //} else if (type_ == 4) {
                    //    // handled above
                    //    ret.assetId = data;
                } else if (type_ == 5) {
                    ret.groupKey = data;
                } else if (type_ == 6) {
                    ret.scriptKey = data;
                } else if (type_ == 8) {
                    ret.internalKey = data;
                } else if (type_ == 9) {
                    ret.tapscriptSibling = data;
                } else if (type_ == 11) {
                    // not used any more?
                    ret.assetType = data;
                } else if (type_ == 12) {
                    // proof_courier_send, can be ignored
                } else {
//                    console.log("Unknown TLV type: %s", type_);
                    //revert("unknown TLV type");
                }
            }
        }
    }

    function readBytes(
        bytes memory stream,
        uint256 offset,
        uint256 length
    ) internal pure returns (bytes memory, uint256) {
        if (stream.length < offset + length) {
            revert("EOF when reading stream");
        }
        bytes memory ret = new bytes(length);
        for (uint256 i = 0; i < length; i++) {
            ret[i] = stream[offset + i];
        }
        return (ret, offset + length);
    }

    function readBytes32(
        bytes memory stream,
        uint256 offset
    ) internal pure returns (bytes32, uint256) {
        if (stream.length < offset + 32) {
            revert("EOF when reading stream");
        }
        bytes32 ret;
        for (uint256 i = 0; i < 32; i++) {
            ret |= bytes32(stream[offset + i]) >> (i * 8);
        }
        return (ret, offset + 32);
    }

    function readBigSize(
        bytes memory stream,
        uint256 offset
    ) public pure returns (uint64, uint256) {
        if (offset >= stream.length) {
            revert("EOF when reading BigSize");
        }
        uint8 c = uint8(stream[offset]);
        if (c == 0xfd) {
            if (offset + 3 > stream.length) {
                revert("EOF when reading BigSize (0xfd)");
            }
            uint64 ret = (uint64(uint8(stream[offset + 1])) << 8) | (uint64(uint8(stream[offset + 2])));
            return (ret, offset + 3);
        } else if (c == 0xfe) {
            if (offset + 5 > stream.length) {
                revert("EOF when reading BigSize (0xfe)");
            }
            uint64 ret = (
                (uint64(uint8(stream[offset + 1])) << 24) |
                (uint64(uint8(stream[offset + 2])) << 16) |
                (uint64(uint8(stream[offset + 3])) << 8) |
                (uint64(uint8(stream[offset + 4])))
            );
            return (ret, offset + 5);
        } else if (c == 0xff) {
            if (offset + 9 > stream.length) {
                revert("EOF when reading BigSize (0xff)");
            }
            uint64 ret = (
                (uint64(uint8(stream[offset + 1])) << 56) |
                (uint64(uint8(stream[offset + 2])) << 48) |
                (uint64(uint8(stream[offset + 3])) << 40) |
                (uint64(uint8(stream[offset + 4])) << 32) |
                (uint64(uint8(stream[offset + 5])) << 24) |
                (uint64(uint8(stream[offset + 6])) << 16) |
                (uint64(uint8(stream[offset + 7])) << 8) |
                (uint64(uint8(stream[offset + 8])))
            );
            return (ret, offset + 9);
        } else {
            return (uint64(c), offset + 1);
        }
    }

    // ******************************
    // * / END of TAP address utils *
    // ******************************

    // ****************
    // * BECH32 UTILS *
    // ****************

    //bytes constant BECH32_ALPHABET = bytes("qpzry9x8gf2tvdw0s3jn54khce6mua7l");
    uint8 constant BECH32_FIRST_ORD = 48;
    uint8 constant BECH32_LAST_ORD = 122;
    uint8 constant BECH32_MAX_VALID_MAPPED = 0x1f;
    bytes constant BECH32_ALPHABET_MAP = hex"0fff0a1115141a1e0705ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff1dff180d19090817ff12161f1b13ff010003100b1c0c0e060402";
    uint256 constant BECH32_CHECKSUM_LENGTH = 6;

    /// @dev decode a bech32(m) address, checking the prefix and checksum, and convert bits like they're supposed to
    function decodeBech32Address(
        string memory validPrefix,
        string calldata input,
        uint256 checksumConstant
    ) public pure returns (bytes memory) {
        bytes memory words = decodeBech32(
            validPrefix,
            input,
            checksumConstant
        );
        return convertBits(words, 5, 8, false);
    }

    // Python version (from bech32.convertbits)
    // def convertbits(data: Iterable[int], frombits: int, tobits: int, pad: bool = True) -> Optional[List[int]]:
    //    """General power-of-2 base conversion."""
    //    acc = 0
    //    bits = 0
    //    ret = []
    //    maxv = (1 << tobits) - 1
    //    max_acc = (1 << (frombits + tobits - 1)) - 1
    //    for value in data:
    //        if value < 0 or (value >> frombits):
    //            return None
    //        acc = ((acc << frombits) | value) & max_acc
    //        bits += frombits
    //        while bits >= tobits:
    //            bits -= tobits
    //            ret.append((acc >> bits) & maxv)
    //    if pad:
    //        if bits:
    //            ret.append((acc << (tobits - bits)) & maxv)
    //    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
    //        return None
    //    return ret
    // convert to solidity:
    function convertBits(
        bytes memory words,
        uint256 fromBits,
        uint256 toBits,
        bool pad
    ) internal pure returns (bytes memory) {
        uint256 acc = 0;
        uint256 bits = 0;
        uint256 maxv = (1 << toBits) - 1;
        uint256 maxAcc = (1 << (fromBits + toBits - 1)) - 1;
        // this resulted in an extra 0x00 byte at the end
        // bytes memory ret = new bytes((words.length * fromBits + toBits - 1) / toBits);
        uint256 retSize = (words.length * fromBits) / toBits;
        // TODO: this also results in an extra 0x00 byte at the end, but it seems like this check should be there.
        // At this point, I decide not to care
        // if ((words.length * fromBits) % toBits != 0) {
        //     retSize++;
        // }
        bytes memory ret = new bytes(retSize);
        uint256 retIdx = 0;
        for (uint256 i = 0; i < words.length; i++) {
            uint256 value = uint8(words[i]);
            if (value >> fromBits != 0) {
                revert("invalid value");
            }
            acc = ((acc << fromBits) | value) & maxAcc;
            bits += fromBits;
            while (bits >= toBits) {
                bits -= toBits;
                ret[retIdx] = bytes1(uint8((acc >> bits) & maxv));
                retIdx++;
            }
        }
        if (pad) {
            if (bits != 0) {
                ret[retIdx] = bytes1(uint8((acc << (toBits - bits)) & maxv));
                retIdx++;
            }
        } else if (bits >= fromBits || ((acc << (toBits - bits)) & maxv) != 0) {
            revert("invalid padding");
        }
        return ret;
    }

    /// @dev adapted from https://github.com/bitcoinjs/bech32/blob/master/src/index.ts
    function decodeBech32(
        string memory validPrefix,
        string calldata input,
        uint256 checksumConstant
    ) public pure returns (bytes memory) {
        uint256 chk = 1;

        // parse prefix
        uint256 i = 0;
        for (; i < bytes(input).length; i++) {
            if (i > bytes(validPrefix).length) {
                revert("invalid prefix length (too long)");
            }
            bytes1 c = bytes(input)[i];
            if (c == bytes1("1")) {
                break;
            }
            if (c != bytes(validPrefix)[i]) {
                revert("invalid prefix");
            }

            // probably terribly gas inefficient but whatever
            // in real world we don't need to decode, only check
            chk = polymodStep(chk) ^ (uint8(c) >> 5);
        }
        if (i != bytes(validPrefix).length) {
            revert("invalid checksum length (too short)");
        }
        chk = polymodStep(chk);
        for (uint256 j = 0; j < i; j++) {
            chk = polymodStep(chk) ^ (uint8(bytes(input)[j]) & 0x1f);
        }
        // TODO: prefix polymod could be pre-computed to save gas

        i++;  // skip the checksum separator "1"
        uint256 start = i;
        bytes memory words = new bytes(bytes(input).length - start - BECH32_CHECKSUM_LENGTH);

        for (; i < bytes(input).length; i++) {
            bytes1 c = bytes(input)[i];
            uint8 ord = uint8(c);
            if (ord < BECH32_FIRST_ORD || ord > BECH32_LAST_ORD) {
                revert("invalid char");
            }
            bytes1 mapped = BECH32_ALPHABET_MAP[ord - BECH32_FIRST_ORD];
            if (uint8(mapped) > BECH32_MAX_VALID_MAPPED) {
                revert("invalid char (mapped)");
            }

            chk = polymodStep(chk) ^ uint8(mapped);

            if (i + BECH32_CHECKSUM_LENGTH < bytes(input).length) {
                words[i - start] = mapped;
            }
        }

        //console.log("checksum %d", chk);
        if (chk != checksumConstant) {
            revert("invalid checksum");
        }
        return words;
    }

    function polymodStep(
        uint256 pre
    ) internal pure returns (uint256) {
        uint256 b = pre >> 25;

        // using * 1 instead of ifs. evil!
        return (
            ((pre & 0x1ffffff) << 5) ^
            (((b >> 0) & 1) * 0x3b6a57b2) ^
            (((b >> 1) & 1) * 0x26508e6d) ^
            (((b >> 2) & 1) * 0x1ea119fa) ^
            (((b >> 3) & 1) * 0x3d4233dd) ^
            (((b >> 4) & 1) * 0x2a1462b3)
        );
    }

    // *************************
    // * / END OF BECH32 UTILS *
    // *************************
}
