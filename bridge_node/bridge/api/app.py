from anemic.ioc import Container
from pyramid.config import Configurator
from pyramid.request import Request
from waitress import serve

from bridge.common.services.transactions import TransactionManager


def create_app(
    global_container: Container,
):
    def get_request_container(request: Request) -> Container:
        tx_manager: TransactionManager = global_container.get(interface=TransactionManager)
        tx = tx_manager.transaction()
        tx.begin()

        def commit_callback(req):
            if req.exception is not None:
                tx.rollback()
            else:
                tx.commit()

        request.add_finished_callback(commit_callback)

        return tx.container

    with Configurator() as config:
        config.include("bridge.cors")
        config.add_cors_preflight_handler()
        config.scan("bridge.api")
        config.scan("bridge.bridges.runes")
        config.include("bridge.api.views", route_prefix="/api/v1")
        config.add_route("index", "")
        config.add_request_method(
            get_request_container,
            "container",
            reify=True,
        )
        app = config.make_wsgi_app()

    # Binding to 0.0.0.0 is required for Docker, handle further security
    # in the docker compose or server firewall.
    serve(app, host="0.0.0.0", port=8080)  # noqa: S104
