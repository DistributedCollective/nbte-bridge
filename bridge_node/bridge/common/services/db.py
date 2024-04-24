from anemic.ioc import Container, service
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from bridge.config import Config


@service(scope="global", interface_override=Engine)
def engine_factory(container: Container):
    config: Config = container.get(interface=Config)
    # TODO: isolation level serializable? but this would require retry logic
    return create_engine(config.db_url)


@service(scope="transaction", interface_override=Session)
def session_factory(container: Container):
    engine: Engine = container.get(interface=Engine)
    return Session(bind=engine)
