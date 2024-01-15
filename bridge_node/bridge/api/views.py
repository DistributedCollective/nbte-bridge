from pyramid.view import view_config
from pyramid.response import Response
from pyramid.config import Configurator


@view_config(route_name="hello", renderer="string")
def hello_world(request):
    return Response("Hello, World!")


def includeme(config: Configurator):
    config.add_route("hello_world", "")
