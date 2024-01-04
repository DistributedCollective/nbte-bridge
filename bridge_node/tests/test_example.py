from typing import Tuple, NewType

import pytest
from sqlalchemy.orm.session import Session

from bridge.models import MyModel

DBSetup = NewType("DBSetup", Tuple[MyModel])


@pytest.fixture()
def db_setup(dbsession: Session):
    my_model = dbsession.merge(
        MyModel(
            key="mykey",
            value=100,
        )
    )
    dbsession.flush()
    return my_model


def test_create_formula_and_get_data(db_setup: DBSetup):
    my_model = db_setup
    assert my_model.key == "mykey"
    assert my_model.value == 100
