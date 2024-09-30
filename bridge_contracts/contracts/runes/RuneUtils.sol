// SPDX-License-Identifier: GPL-3.0-or-later
pragma solidity 0.8.19;

contract RuneUtils {
    struct RuneId {
        uint64 block;
        uint32 tx;
    }

    struct Rune {
        uint128 number;
    }

    struct SpacedRune {
        uint128 rune;
        uint32 spacers;
    }

    struct RuneInfo {
        uint128 number;
        uint32 spacers;
        uint64 etchingBlock;
        uint32 etchingTx;
        string name;
        string spacedName;
    }

    /// @dev Converts a Rune's uint128 representation to its human-readable base26-decoded name
    /// @dev Implementation copied from ordinals/ord, rune.rs, `impl Display for Rune`
    function runeNumberToName(uint128 number) public pure returns (string memory) {
        //    let mut n = self.0;
        //    if n == u128::MAX {
        //      return write!(f, "BCGDENLQRQWDSLRUGSNLBTMFIJAV");
        //    }
        if (number == type(uint128).max) {
            return "BCGDENLQRQWDSLRUGSNLBTMFIJAV";
        }
        //    n += 1;
        number += 1;

        uint256 length = 0;
        //    let mut symbol = String::new();
        bytes memory buffer = new bytes(28);
        //    while n > 0 {
        //      symbol.push(
        //        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        //          .chars()
        //          .nth(((n - 1) % 26) as usize)
        //          .unwrap(),
        //      );
        //      n = (n - 1) / 26;
        //    }
        bytes memory alphabet = bytes("ABCDEFGHIJKLMNOPQRSTUVWXYZ");
        while (number > 0) {
            buffer[length] = bytes1(alphabet[(number - 1) % 26]);
            length++;
            number = (number - 1) / 26;
        }

        //     for c in symbol.chars().rev() {
        //      write!(f, "{c}")?;
        //    }
        bytes memory ret = new bytes(length);
        for (uint256 i = 0; i < length; i++) {
            ret[i] = buffer[length - i - 1];
        }
        return string(ret);
    }

    /// @dev Converts a Rune's human-readable name to its
    /// @dev Implementation copied from ordinals/ord, rune.rs, `impl FromStr for Rune`
    function runeNameToNumber(string calldata s) public pure returns (uint128 num) {
        num = 0;
        bytes memory b = bytes(s);
        //     for (i, c) in s.chars().enumerate() {
        for (uint256 i = 0; i < b.length; i++) {
            bytes1 c = b[i];
            //      if i > 0 {
            //        x += 1;
            //      }
            if (i > 0) {
                num += 1;
            }
            //      x = x.checked_mul(26).ok_or(Error::Range)?;
            num *= 26;
            //      match c {
            //        'A'..='Z' => {
            //          x = x.checked_add(c as u128 - 'A' as u128).ok_or(Error::Range)?;
            //        }
            //        _ => return Err(Error::Character(c)),
            //      }
            if (c >= 'A' && c <= 'Z') {
                num += uint8(c) - uint8(bytes1('A'));
            } else {
                revert("Invalid character in rune name");
            }
        }
    }

    function spacedRuneToNumberAndSpacers(string calldata s)
    public
    pure
    returns (uint128 num, uint32 spacers) {
        num = 0;
        spacers = 0;
        uint32 length = 0;
        bytes memory b = bytes(s);
        for (uint256 i = 0; i < b.length; i++) {
            bytes1 c = b[i];
            bool isSpacer = false;
            if (c == '.') {
                isSpacer = true;
            } else if (c == 0xe2) {
                if (i > b.length - 2) {
                    revert("Invalid spacer character (length)");
                }
                if (b[i + 1] == 0x80 && b[i + 2] == 0xa2) {
                    // '•'
                    isSpacer = true;
                    i += 2;
                } else {
                    revert("Invalid spacer character");
                }
            }
            if (isSpacer) {
                if (i == 0 || i == b.length - 1) {
                    revert("Leading or trailing spacer");
                }
                uint32 flag = uint32(1 << (length - 1));
                if (spacers & flag != 0) {
                    revert("Double spacer");
                }
                spacers |= flag;
            } else if (c >= 'A' && c <= 'Z') {
                if (i > 0) {
                    num += 1;
                }
                num *= 26;
                num += uint8(c) - uint8(bytes1('A'));
                length++;
            } else {
                revert("Invalid character in rune name");
            }
        }
    }

    function numberAndSpacersToSpacedRune(
        uint128 number,
        uint32 spacers
    )
    public
    pure
    returns (string memory) {
        bytes memory runeBuffer = bytes(runeNumberToName(number));
        uint256 length = runeBuffer.length;

        bytes memory spacedBuffer = new bytes(length * 2);
        uint256 spacedLength = 0;
        uint256 i;
        for(i = 0; i < length; i++) {
            spacedBuffer[spacedLength] = runeBuffer[i];
            spacedLength++;
            if (i < length - 1 && (spacers & (1 << i)) != 0) {
                spacedBuffer[spacedLength] = '.';
                spacedLength++;
            }
        }

        bytes memory ret = new bytes(spacedLength);
        for (i = 0; i < spacedLength; i++) {
            ret[i] = spacedBuffer[i];
        }
        return string(ret);
    }
}
