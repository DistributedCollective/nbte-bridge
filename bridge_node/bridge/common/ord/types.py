import pyord

Runish = pyord.Rune | str | int


def coerce_rune(rune: Runish) -> pyord.Rune:
    if isinstance(rune, int):
        return pyord.Rune(rune)
    elif isinstance(rune, str):
        return rune_from_str(rune)
    if not isinstance(rune, pyord.Rune):
        raise ValueError("rune must be a Rune instance, a str or an int")
    return rune


def rune_from_str(s: str) -> pyord.Rune:
    """
    Convert a possibly-spaced rune string to Rune
    """
    if not isinstance(s, str):
        raise ValueError(f"expecting an str, got {type(s)}: {s!r}")
    s = remove_spacers(s)
    return pyord.Rune.from_str(s)


def remove_spacers(rune: str) -> str:
    ret = "".join(c for c in rune if c not in (".", "•"))
    if not ret.isalpha():
        raise ValueError(f"rune {rune} contains non-alphabetic characters")
    if not ret.isupper():
        raise ValueError(f"rune {rune} contains lowercase characters")
    return ret
