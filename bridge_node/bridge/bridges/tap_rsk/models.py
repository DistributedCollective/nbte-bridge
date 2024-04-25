from enum import IntEnum
from typing import TypedDict

from eth_abi.packed import encode_packed
from eth_utils import keccak, to_hex
from hexbytes import HexBytes
from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from bridge.common.models.meta import Base

# NOTE: do not change this without understanding the consequences!
PREFIX = "taprsk"


class RskToTapTransferBatchStatus(IntEnum):
    CREATED = 1
    # VPSBT_CREATED = 2
    # VPSBT_FINALIZED = 3
    SENDING_TO_TAP = 4
    SENT_TO_TAP = 5
    # MINED = 6
    # PROOFS_PUBLISHED = 7
    FINALIZED = 8

    @staticmethod
    def status_to_str(status: int) -> str:
        try:
            return RskToTapTransferBatchStatus(status).name.lower()
        except ValueError:
            return "seen"


class TapToRskTransferBatchStatus(IntEnum):
    CREATED = 1
    SIGNATURES_COLLECTED = 2
    SENDING_TO_RSK = 3
    SENT_TO_RSK = 4
    MINED = 5
    # UNIVERSE_SYNCED = 6
    FINALIZED = 7

    @staticmethod
    def status_to_str(status: int) -> str:
        try:
            return TapToRskTransferBatchStatus(status).name.lower()
        except ValueError:
            return "seen"


class SerializedDepositAddress(TypedDict):
    rsk_address: str
    tap_address: str


class SerializedTapToRskTransfer(TypedDict):
    hash: str
    deposit_address: SerializedDepositAddress
    deposit_btc_tx_id: str
    deposit_btc_tx_vout: int


class SerializedTapToRskTransferBatch(TypedDict):
    hash: str
    status: int
    signatures: dict[str, list[str]]
    transfers: list[SerializedTapToRskTransfer]


class RskToTapTransferBatch(Base):
    __tablename__ = f"{PREFIX}_rsk_to_tap_transfer_batch"

    id = Column(Integer, primary_key=True)
    # TODO: hash
    status = Column(
        "status",
        Integer,
        nullable=False,
        default=RskToTapTransferBatchStatus.CREATED,
    )

    transfers = relationship("RskToTapTransfer", back_populates="transfer_batch", order_by="RskToTapTransfer.counter")
    # TODO: vpsbt
    sending_result = Column(JSONB, nullable=False, server_default="{}", default=dict)


class TapToRskTransferBatch(Base):
    __tablename__ = f"{PREFIX}_tap_to_rsk_transfer_batch"

    id = Column(Integer, primary_key=True)
    hash = Column(LargeBinary(length=32), nullable=False, unique=True)
    status = Column(
        "status",
        Integer,
        nullable=False,
        default=TapToRskTransferBatchStatus.CREATED,
    )
    signatures = Column(JSONB, nullable=False, server_default="{}", default=dict)

    transfers = relationship("TapToRskTransfer", back_populates="transfer_batch", order_by="TapToRskTransfer.counter")
    executed_tx_hash = Column(Text, nullable=True)

    def compute_hash(self) -> bytes:
        return keccak(
            encode_packed(
                ["bytes32", "bytes32[]"],
                [b"TapToRskTransferBatch:", [t.compute_hash() for t in self.transfers]],
            )
        )

    def serialize(self) -> SerializedTapToRskTransferBatch:
        return {
            "hash": to_hex(self.hash),
            "status": self.status,
            "signatures": self.signatures,
            "transfers": [t.serialize() for t in self.transfers],
        }

    def __repr__(self):
        return f"TapToRskTransferBatch({self.serialize()})"


class BridgeableAsset(Base):
    __tablename__ = f"{PREFIX}_bridgeable_asset"

    db_id = Column(Integer, primary_key=True)
    rsk_token_address = Column(Text, nullable=False)
    tap_asset_id = Column(Text, nullable=False)
    tap_amount_divisor = Column(Integer, nullable=False)
    tap_asset_name = Column(Text, nullable=False)

    rsk_event_block_number = Column(Integer, nullable=False)
    rsk_event_tx_hash = Column(Text, nullable=False)
    rsk_event_tx_index = Column(Integer, nullable=False)
    rsk_event_log_index = Column(Integer, nullable=False)


class TapDepositAddress(Base):
    __tablename__ = f"{PREFIX}_tap_deposit_address"
    id = Column(Integer, primary_key=True)
    rsk_address = Column(Text, nullable=False)
    tap_address = Column(Text, nullable=False, unique=True)
    tap_asset_id = Column(Text, nullable=False)
    rsk_token_address = Column(Text, nullable=False)
    tap_amount = Column(Text, nullable=False)
    rsk_amount = Column(Text, nullable=False)


class RskToTapTransfer(Base):
    __tablename__ = f"{PREFIX}_rsk_to_tap_transfer"

    db_id = Column(Integer, primary_key=True)
    counter = Column(Integer, nullable=False, unique=True)
    # status = Column(
    #     IntEnum(RskToTapTransferStatus),
    #     nullable=False,
    #     native_enum=False,
    #     default=RskToTapTransferStatus.SEEN,
    # )

    recipient_tap_address = Column(Text, nullable=False)
    sender_rsk_address = Column(Text, nullable=False)
    rsk_event_block_number = Column(Integer, nullable=False)
    rsk_event_tx_hash = Column(Text, nullable=False)
    rsk_event_tx_index = Column(Integer, nullable=False)
    rsk_event_log_index = Column(Integer, nullable=False)

    transfer_batch_id = Column(Integer, ForeignKey(f"{PREFIX}_rsk_to_tap_transfer_batch.id"), nullable=True, index=True)
    transfer_batch = relationship(RskToTapTransferBatch, back_populates="transfers")

    # executed_evm_tx_hash = Column(Text)
    # executed_evm_tx_index = Column(Integer)
    # executed_evm_log_index = Column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "rsk_event_tx_hash",
            "rsk_event_tx_index",
            "rsk_event_log_index",
            name=f"uq_{PREFIX}_rsk_to_tap_transfer_event",
        ),
    )

    def __repr__(self):
        return f"RskToTapTransfer({self.counter}, {self.status}, {self.recipient_tap_address})"


class TapToRskTransfer(Base):
    __tablename__ = f"{PREFIX}_tap_to_rsk_transfer"

    db_id = Column(Integer, primary_key=True)
    counter = Column(Integer, nullable=True, unique=True)

    # TODO: tap deposit address
    deposit_address_id = Column(
        Integer,
        ForeignKey(f"{PREFIX}_tap_deposit_address.id"),
        nullable=False,
    )
    deposit_address = relationship(TapDepositAddress)

    deposit_btc_tx_id = Column(Text, nullable=False)
    deposit_btc_tx_vout = Column(Integer, nullable=False)
    # status = Column(
    #     IntEnum(TapToRskTransferStatus),
    #     nullable=False,
    #     native_enum=False,
    #     default=TapToRskTransferStatus.SEEN,
    # )

    transfer_batch_id = Column(Integer, ForeignKey(f"{PREFIX}_tap_to_rsk_transfer_batch.id"), nullable=True, index=True)
    transfer_batch = relationship(TapToRskTransferBatch, back_populates="transfers")

    # rsk_executed_event_block_number = Column(Integer)
    # rsk_executed_event_tx_hash = Column(Text)
    # rsk_executed_event_tx_index = Column(Integer)
    # rsk_executed_event_log_index = Column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "deposit_btc_tx_id",
            "deposit_btc_tx_vout",
            name=f"uq_{PREFIX}_tap_to_rsk_transfer_txid_vout",
        ),
    )

    def __repr__(self):
        return (
            f"TapToRskTransfer({self.counter}, {self.deposit_address.tap_address} "
            f"-> {self.deposit_address.rsk_address}))"
        )

    def compute_hash(self):
        return keccak(
            encode_packed(
                [
                    "bytes32",
                    "address",
                    "bytes32",
                    "string",
                    "bytes32",
                    "bytes32",
                    "bytes32",
                    "uint256",
                ],
                [
                    b"TapToRskTransfer:",
                    self.deposit_address.rsk_address,
                    b":",
                    self.deposit_address.tap_address,
                    b":",
                    HexBytes(self.deposit_btc_tx_id),
                    b":",
                    self.deposit_btc_tx_vout,
                ],
            )
        )

    def serialize(self) -> SerializedTapToRskTransfer:
        return {
            "hash": to_hex(self.compute_hash()),
            "deposit_address": {
                "rsk_address": self.deposit_address.rsk_address,
                "tap_address": self.deposit_address.tap_address,
            },
            "deposit_btc_tx_id": self.deposit_btc_tx_id,
            "deposit_btc_tx_vout": self.deposit_btc_tx_vout,
        }
