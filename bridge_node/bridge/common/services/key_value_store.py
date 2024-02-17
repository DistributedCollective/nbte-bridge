from typing import Any

from anemic.ioc import service, auto, autowired, Container
from sqlalchemy.orm import Session

from ..models.key_value_store import KeyValuePair


_unset = object()


@service(scope="transaction")
class KeyValueStore:
    dbsession: Session = autowired(auto)

    def __init__(self, container: Container):
        self.container = container

    def get_value(self, key: str, default_value: Any = _unset):
        pair = self.dbsession.query(KeyValuePair).filter_by(key=key).first()
        if not pair:
            if default_value is not _unset:
                return default_value
            raise LookupError(f"value for key {key!r} not found")
        return pair.value

    def set_value(self, key: str, value: Any):
        pair = self.dbsession.query(KeyValuePair).filter_by(key=key).first()
        if pair:
            pair.value = value
        else:
            pair = KeyValuePair(key=key, value=value)
        self.dbsession.add(pair)
        self.dbsession.flush()

    def get_or_create_value(self, key: str, default_value: Any) -> Any:
        pair = self.dbsession.query(KeyValuePair).filter_by(key=key).first()
        if not pair:
            pair = KeyValuePair(key=key, value=default_value)
            self.dbsession.add(pair)
            self.dbsession.flush()
        return pair.value
