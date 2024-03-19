from decimal import Decimal


def to_decimal(amount: int, decimals: int) -> Decimal:
    return Decimal(amount) / Decimal(10**decimals)


def to_base_units(amount: Decimal | int | str, decimals: int) -> int:
    return int(Decimal(amount) * 10**decimals)
