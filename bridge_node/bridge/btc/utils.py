import decimal
from typing import Union

from bitcointx import segwit_addr, get_current_chain_params


def to_satoshi(btc: Union[int, decimal.Decimal, str]) -> int:
    if not isinstance(btc, (int, decimal.Decimal, str)):
        raise TypeError(f"Invalid type: {type(btc)}")
    with decimal.localcontext() as ctx:
        ctx.prec = 999
        decimal_value = decimal.Decimal(btc) * 10**8
        integer_value = int(decimal_value)
        if not decimal.Decimal(integer_value) == decimal_value:
            raise ValueError(f"Too precise of a value: {btc}")
        return integer_value


def from_satoshi(satoshi: int) -> decimal.Decimal:
    if not isinstance(satoshi, int):
        raise TypeError(f"Invalid type: {type(satoshi)}")
    with decimal.localcontext() as ctx:
        ctx.prec = 999
        return decimal.Decimal(satoshi) / 10**8


def encode_segwit_address(script, *, witver=0, hrp=None):
    if hrp is None:
        params = get_current_chain_params()
        if params.name == "bitcoin/regtest":
            hrp = "bcrt"
        elif params.name == "bitcoin/testnet":
            hrp = "tb"
        elif params.name == "bitcoin/mainnet":
            hrp = "bc"
        else:
            raise ValueError(f"Unknown network: {params.name}")
    return segwit_addr.encode(hrp, witver, script)
