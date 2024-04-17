from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    Text,
    ForeignKey,
    UniqueConstraint,
    DateTime,
    func,
)
from sqlalchemy.orm import relationship

from bridge.common.models.meta import Base
from bridge.common.models.types import (
    EVMAddress,
)

# Do not change this, it alters all table names
PREFIX = "runes"


class Bridge(Base):
    # TODO: move outside of the rune bridge models
    __tablename__ = "bridge"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # bridgeable_runes = relationship(
    #     "BridgeableRune",
    #     back_populates="bridge",
    #     lazy="dynamic",
    # )


class User(Base):
    # TODO: move outside of the rune bridge models
    __tablename__ = "user"

    id = Column(BigInteger, primary_key=True)
    bridge_id = Column(
        Integer,
        ForeignKey("bridge.id"),
        nullable=False,
    )
    evm_address = Column(EVMAddress, nullable=False, index=True)

    deposit_address = relationship("DepositAddress", uselist=False, back_populates="user")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("bridge_id", "evm_address", name="uq_runes_user_evm_address"),
    )


class DepositAddress(Base):
    # TODO: move outside of the rune bridge models
    __tablename__ = "deposit_address"

    user_id = Column(Integer, ForeignKey("user.id"), primary_key=True)
    btc_address = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="deposit_address")


# class BridgeableRune(Base):
#     __tablename__ = f"{PREFIX}_bridgeable_rune"
#
#     id = Column(BigInteger, primary_key=True)
#
#     bridge_id = Column(
#         Integer, ForeignKey(f"{PREFIX}_bridge.id"), nullable=False
#     )
#
#     rune_number = Column(
#         Uint128,
#         nullable=False,
#     )  # Normalized name as base26 encoded integer
#
#     token_address = Column(EVMAddress, nullable=False, index=True)
#     token_name = Column(Text, nullable=False)
#     token_symbol = Column(Text, nullable=False)
#
#     bridge = relationship("Bridge", back_populates="bridgeable_runes")
#     created_at = Column(
#         DateTime(timezone=True), nullable=False, server_default=func.now()
#     )
#
#     __table_args__ = (
#         UniqueConstraint("bridge_id", "rune_number"),
#     )
#
# class RuneDeposit(Base):
#     __tablename__ = f"{PREFIX}_rune_deposit"
#
#     id = Column(BigInteger, primary_key=True)
#     tx_hash = Column(Text, nullable=False)
#     block_number = Column(Integer, nullable=False)
#     tx_index = Column(Integer, nullable=False)
#     vout = Column(Integer, nullable=False)
#
#     user_id = Column(Integer, ForeignKey(f"{PREFIX}_user.id"), nullable=True)
#     bridge_id = Column(
#         Integer, ForeignKey(f"{PREFIX}_bridge.id"), nullable=False
#     )
#
#     rune_number = Column(Uint128, nullable=False)
#     amount_raw = Column(Uint128, nullable=False)
#     created_at = Column(
#         DateTime(timezone=True), nullable=False, server_default=func.now()
#     )
#
#     __table_args__ = (
#         UniqueConstraint(
#             "bridge_id", "tx_hash", "vout", "rune_number",
#             name="uq_runes_rune_deposit_tx_hash"
#         ),
#     )
