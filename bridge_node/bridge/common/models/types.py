import decimal

import eth_utils
from sqlalchemy import types


class UintMixin:
    # Adapted from https://gist.github.com/miohtama/0f1900fb746941e24757bddaaef4d08b
    MAX_VALUE: int  # override in subclasses

    impl = types.NUMERIC
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None:
            return self._coerce_and_validate_uint(value)
        return None

    def process_bind_param(self, value, dialect):
        if isinstance(value, decimal.Decimal):
            return self._coerce_and_validate_uint(value)
        return value

    def _coerce_and_validate_uint(self, value):
        value = int(value)
        if value < 0 or value > self.MAX_VALUE:
            raise f"Value {value} is out of range for {self.__class__.__name__}"
        return value


class Uint256(UintMixin, types.TypeDecorator):
    MAX_VALUE = 2**256 - 1
    cache_ok = True


class Uint128(UintMixin, types.TypeDecorator):
    MAX_VALUE = 2**128 - 1
    cache_ok = True


class EVMAddress(types.TypeDecorator):
    impl = types.LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, bytes):
            if not eth_utils.is_canonical_address(value):
                raise ValueError(f"{value!r} is not a valid canonical EVM address")
            return value
        elif isinstance(value, str):
            if not eth_utils.is_checksum_address(value):
                raise ValueError(f"{value!r} is not a valid checksummed EVM address")
            return eth_utils.to_canonical_address(value)
        else:
            raise TypeError(
                f"Unsupported type {type(value)} for EVM address, expected address as bytes or checksummed string"
            )

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return eth_utils.to_checksum_address(value)
