from pyramid.config import Configurator
from . import views


def includeme(config: Configurator):
    config.include(views, route_prefix="/")
