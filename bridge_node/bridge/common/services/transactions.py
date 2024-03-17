# NOTE: THIS MODULE IS DEPRECATED. dbsession can be used directly from the global container.
from typing import Type, TypeVar
import warnings

from anemic.ioc import Container, FactoryRegistry
from sqlalchemy.orm.session import Session

T = TypeVar("T")


class Transaction:
    def __init__(self, *, global_container: Container, transaction_registry: FactoryRegistry):
        warnings.warn(
            "Transaction is deprecated."
            "Use SQLAlchemy Session directly in global services with self.dbsession.begin()",
            DeprecationWarning,
        )
        self._global_container = global_container
        self._transaction_registry = transaction_registry
        self._transaction_container = None
        self._dbsession = None

    @property
    def container(self) -> Container:
        self._ensure_transaction()
        return self._transaction_container

    def find_service(self, interface: Type[T]) -> T:
        self._ensure_transaction()
        return self._transaction_container.get(interface=interface)

    def __enter__(self) -> "Transaction":
        self.begin()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def begin(self):
        if self._transaction_container is not None:
            raise RuntimeError("transaction already started")
        self._transaction_container = Container(
            self._transaction_registry,
            parent=self._global_container,
        )
        self._dbsession = self._transaction_container.get(interface=Session)
        self._dbsession.begin()

    def commit(self):
        self._ensure_transaction()
        self._dbsession.commit()
        self._transaction_container = None
        self._dbsession = None

    def rollback(self):
        if self._transaction_container is None:
            raise RuntimeError("transaction not started")
        self._dbsession.rollback()
        self._transaction_container = None
        self._dbsession = None

    def _ensure_transaction(self):
        if self._transaction_container is None:
            raise RuntimeError("transaction not started")


class TransactionManager:
    def __init__(self, *, global_container: Container, transaction_registry: FactoryRegistry):
        warnings.warn(
            "TransactionManager is deprecated. "
            "Use SQLAlchemy Session directly in global services with self.dbsession.begin()",
            DeprecationWarning,
        )
        self._global_container = global_container
        self._transaction_registry = transaction_registry

    def transaction(self) -> Transaction:
        return Transaction(
            global_container=self._global_container,
            transaction_registry=self._transaction_registry,
        )


# This cannot be annotated with @service unless transaction_registry is registered as a service,
# which seems counter-intuitive
def register_transaction_manager(
    *,
    global_registry: FactoryRegistry,
    transaction_registry: FactoryRegistry,
):
    # This is a proper factory factory...
    def transaction_manager_factory(container: Container) -> TransactionManager:
        return TransactionManager(
            global_container=container,
            transaction_registry=transaction_registry,
        )

    global_registry.register(
        interface=TransactionManager,
        factory=transaction_manager_factory,
    )
