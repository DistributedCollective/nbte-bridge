from sqlalchemy import Column, Integer, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from bridge.common.models.meta import Base
from bridge.common.models.types import EVMAddress

# Do not change this, it alters all table names
PREFIX = "runes"


class User(Base):
    # TODO: doesn't need to be constrained to rune bridge, really
    __tablename__ = f"{PREFIX}_user"

    id = Column(Integer, primary_key=True)
    bridge_id = Column(Text, nullable=False)
    evm_address = Column(EVMAddress, nullable=False)  # TODO: use custom evm address type

    deposit_address = relationship("DepositAddress", uselist=False, back_populates="user")

    __table_args__ = (
        UniqueConstraint("bridge_id", "evm_address", name="uq_runes_user_evm_address"),
    )


class DepositAddress(Base):
    __tablename__ = f"{PREFIX}_deposit_address"

    user_id = Column(Integer, ForeignKey(f"{PREFIX}_user.id"), primary_key=True)
    btc_address = Column(Text, nullable=False, unique=True)

    user = relationship("User", back_populates="deposit_address")


# class RuneDeposit(Base):
#     __tablename__ = f"{PREFIX}_rune_deposit"
#
#     tx_hash = Column(Text, primary_key=True)
#     block_number = Column(BigInteger, nullable=False)
#     tx_index = Column(BigInteger, nullable=False)
#     user_id = Column(Integer, ForeignKey(f'{PREFIX}_user.id'), nullable=False)
#     rune_number = Column(Uint128, nullable=False)
#     amount_raw = Column(Uint128, nullable=False)
#
#     __table_args__ = (
#         UniqueConstraint("bridge_id", "tx_hash"),
#     )


# These are kept here temporarily:

# class BridgeableRune(Base):
#     __tablename__ = f"{PREFIX}_bridgeable_rune"
#
#     rune_number = Column(Uint128, nullable=False)  # Normalized name as base26 encoded integer
#     normalized_name = Column(Text, nullable=False)
#     spaced_name = Column(Text, nullable=False)
#     spacers = Column(BigInteger, nullable=False)
#     divisibility = Column(Integer, nullable=False)
#     symbol = Column(Text, nullable=False)
#     etching_block_number = Column(BigInteger, nullable=False)
#     etching_tx_index = Column(BigInteger, nullable=False)
#
#     __table_args__ = (
#         UniqueConstraint("bridge_id", "normalized_name"),
#     )


# class RunesToEvmTransfer(Base):
#     __tablename__ = f"{PREFIX}_runes_to_evm_transfer"
#
#     rune_name = Column(Text, nullable=False)
#     tx_id = Column(Text, nullable=False)
#     amount_raw = Column(Uint128, nullable=False)
#
#     evm_address = Column(Text, nullable=False)
#     block_number = Column(BigInteger, nullable=False)
#     tx_index = Column(BigInteger, nullable=False)
#
#     __table_args__ = (
#         UniqueConstraint("bridge_id", "tx_hash"),
#     )
