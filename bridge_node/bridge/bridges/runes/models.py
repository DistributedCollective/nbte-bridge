from decimal import Decimal
from enum import IntEnum

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    Text,
    ForeignKey,
    UniqueConstraint,
    DateTime,
    func,
    Boolean,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.mutable import MutableList

from bridge.common.models.meta import Base
from bridge.common.models.types import (
    EVMAddress,
    Uint128,
)


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


class IncomingBtcTxStatus(IntEnum):
    DETECTED = 1
    ACCEPTED = 2


class RuneDepositStatus(IntEnum):
    DETECTED = 10
    ACCEPTED = 20
    SENDING_TO_EVM = 30
    SENT_TO_EVM = 40
    CONFIRMED_IN_EVM = 50
    REJECTED = -1
    SENDING_TO_EVM_FAILED = -2
    EVM_TRANSACTION_FAILED = -3


class RuneTokenDepositStatus(IntEnum):
    DETECTED = 10
    ACCEPTED = 20
    SENDING_TO_BTC = 30
    SENT_TO_BTC = 40
    MINED_IN_BTC = 50
    REJECTED = -1
    SENDING_TO_BTC_FAILED = -2


class IncomingBtcTx(Base):
    __tablename__ = "incoming_btc_tx"

    id = Column(BigInteger, primary_key=True)
    bridge_id = Column(Integer, ForeignKey("bridge.id"), nullable=False)

    tx_id = Column(Text, nullable=False)
    vout = Column(Integer, nullable=False)
    block_number = Column(Integer, nullable=True)
    time = Column(Integer, nullable=False)

    address = Column(Text, nullable=False)

    amount_sat = Column(BigInteger, nullable=False)

    user_id = Column(Integer, ForeignKey("user.id"), nullable=True)
    user = relationship("User")

    status = Column(Integer, nullable=False, default=IncomingBtcTxStatus.DETECTED)

    rune_deposits = relationship("RuneDeposit", back_populates="incoming_btc_tx")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("bridge_id", "tx_id", "vout", name="uq_incoming_bitcoin_tx_id_vout"),
    )


class Rune(Base):
    __tablename__ = "rune"

    id = Column(BigInteger, primary_key=True)
    bridge_id = Column(Integer, ForeignKey("bridge.id"), nullable=False)

    n = Column(Uint128, nullable=False)  # name base26 encoded
    name = Column(Text, nullable=False)
    spaced_name = Column(Text, nullable=False)
    symbol = Column(Text, nullable=False)
    divisibility = Column(Integer, nullable=False)
    turbo = Column(Boolean, nullable=False)

    __table_args__ = (UniqueConstraint("bridge_id", "n", name="uq_rune_n"),)

    def __repr__(self):
        return f"Rune(id={self.id}, n={self.n}, name={self.name!r}, symbol={self.symbol!r})"

    def decimal_amount(self, amount_raw: int) -> Decimal:
        return Decimal(amount_raw) / 10**self.divisibility


class RuneDeposit(Base):
    __tablename__ = "rune_deposit"

    id = Column(BigInteger, primary_key=True)
    bridge_id = Column(Integer, ForeignKey("bridge.id"), nullable=False)

    tx_id = Column(Text, nullable=False)
    vout = Column(Integer, nullable=False)
    block_number = Column(Integer, nullable=False)

    rune_number = Column(Uint128, nullable=False)

    rune_id = Column(Integer, ForeignKey("rune.id"), nullable=False)
    rune = relationship(Rune)

    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    user = relationship(User)

    incoming_btc_tx_id = Column(Integer, ForeignKey("incoming_btc_tx.id"), nullable=False)
    incoming_btc_tx = relationship(IncomingBtcTx, back_populates="rune_deposits")

    postage = Column(BigInteger, nullable=False)

    transfer_amount_raw = Column(Uint128, nullable=False)
    net_amount_raw = Column(Uint128, nullable=False)

    evm_tx_hash = Column(Text, nullable=True)

    accept_transfer_message_hash = Column(Text, nullable=True)
    accept_transfer_signatures = Column(
        MutableList.as_mutable(JSONB), nullable=False, server_default="[]"
    )
    accept_transfer_signers = Column(
        MutableList.as_mutable(JSONB), nullable=False, server_default="[]"
    )

    status = Column(
        Integer,
        nullable=False,
        default=RuneDepositStatus.DETECTED.value,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "bridge_id",
            "tx_id",
            "vout",
            "rune_number",
            name="uq_rune_deposit_txid_vout_rune_number",
        ),
    )

    def __repr__(self):
        rune_name = self.rune.spaced_name
        net_amount = self.rune.decimal_amount(self.net_amount_raw)
        return f"RuneDeposit({net_amount} {rune_name} => {self.user.evm_address} ({self.tx_id}:{self.vout}, status={self.status}))"

    @property
    def fee_raw(self) -> int:
        return self.transfer_amount_raw - self.net_amount_raw

    def get_status_for_ui(self) -> str:
        # XXX maps status to a string that can be used in the UI
        status_map = {
            RuneDepositStatus.DETECTED: "detected",
            RuneDepositStatus.ACCEPTED: "seen",
            RuneDepositStatus.SENDING_TO_EVM: "seen",
            RuneDepositStatus.SENT_TO_EVM: "sent_to_evm",
            RuneDepositStatus.CONFIRMED_IN_EVM: "confirmed",
            # RuneDepositStatus.EVM_TRANSFER_FAILED: "evm_transfer_failed",
        }
        return status_map.get(self.status, "Processing")


class RuneTokenDeposit(Base):
    __tablename__ = "rune_token_deposit"

    id = Column(BigInteger, primary_key=True)
    bridge_id = Column(Integer, ForeignKey("bridge.id"), nullable=False)

    evm_tx_hash = Column(Text, nullable=True)
    evm_log_index = Column(Integer, nullable=True)

    receiver_btc_address = Column(Text, nullable=False)
    net_rune_amount_raw = Column(Uint128, nullable=False)
    token_address = Column(EVMAddress, nullable=False)
    rune_id = Column(Integer, ForeignKey("rune.id"), nullable=False)
    rune = relationship(Rune)

    status = Column(
        Integer,
        nullable=False,
        default=RuneTokenDepositStatus.DETECTED.value,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    (
        UniqueConstraint(
            "evm_tx_hash",
            "evm_log_index",
            name="uq_rune_token_deposit_tx_hash_log_index",
        ),
    )

    serialized_psbt = Column(Text, nullable=False)
    # TODO: PSBT signers
