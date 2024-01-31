from sqlalchemy import (
    Column,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from .meta import Base


class KeyValuePair(Base):
    __tablename__ = "key_value_pair"

    key = Column(Text, primary_key=True)
    value = Column(JSONB)
