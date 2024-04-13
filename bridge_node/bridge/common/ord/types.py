import pyord

Runish = pyord.Rune | str | int


def coerce_rune(rune: Runish) -> pyord.Rune:
    if isinstance(rune, int):
        return pyord.Rune(rune)
    elif isinstance(rune, str):
        return pyord.Rune.from_str(rune)
    if not isinstance(rune, pyord.Rune):
        raise ValueError("rune must be a Rune instance, a str or an int")
    return rune
