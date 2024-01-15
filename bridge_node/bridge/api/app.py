from waitress import serve
from pyramid.config import Configurator


def create_app():
    with Configurator() as config:
        config.add_route("hello", "/")
        config.scan("bridge")
        app = config.make_wsgi_app()

    serve(app, host="0.0.0.0", port=8080)
