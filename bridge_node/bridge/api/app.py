from waitress import serve
from pyramid.request import Request
from pyramid.config import Configurator
from anemic.ioc import Container, FactoryRegistry


def create_app(
    global_container: Container,
):
    request_registry = FactoryRegistry(
        "request"
    )  # TODO: dummy factory, think about db sessions later

    def get_request_container(request: Request) -> Container:
        return Container(
            request_registry,
            parent=global_container,
        )

    with Configurator() as config:
        config.scan("bridge.api")
        config.include("bridge.api.views", route_prefix="/api/v1")
        config.add_route("index", "")
        config.add_request_method(
            get_request_container,
            "container",
            reify=True,
        )
        app = config.make_wsgi_app()

    serve(app, host="0.0.0.0", port=8080)
