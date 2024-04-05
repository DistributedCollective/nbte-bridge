"""
Generate the BECH32_ALPHABET_MAP hex that can be added to BTCAddressValidator.sol
"""
ALPHABET_MAP = {
    "0": 15,
    "2": 10,
    "3": 17,
    "4": 21,
    "5": 20,
    "6": 26,
    "7": 30,
    "8": 7,
    "9": 5,
    "q": 0,
    "p": 1,
    "z": 2,
    "r": 3,
    "y": 4,
    "x": 6,
    "g": 8,
    "f": 9,
    "t": 11,
    "v": 12,
    "d": 13,
    "w": 14,
    "s": 16,
    "j": 18,
    "n": 19,
    "k": 22,
    "h": 23,
    "c": 24,
    "e": 25,
    "m": 27,
    "u": 28,
    "a": 29,
    "l": 31,
}
FIRST_ORD = 48
LAST_ORD = 122
MAX_MAPPED = 0x1F
ALPHABET_MAP_BYTES = bytearray(0xFE for _ in range(LAST_ORD - FIRST_ORD + 1))
for i in range(FIRST_ORD, LAST_ORD + 1):
    c = chr(i)
    mapped = ALPHABET_MAP.get(c)
    if mapped is None:
        mapped = 0xFF
    ALPHABET_MAP_BYTES[i - FIRST_ORD] = mapped
print(ALPHABET_MAP_BYTES.hex())
