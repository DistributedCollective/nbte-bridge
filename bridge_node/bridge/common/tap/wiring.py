from anemic.ioc import Container, service

from bridge.common.tap.client import TapRestClient
from bridge.config import Config


@service(interface_override=TapRestClient, scope="global")
def client_factory(container: Container):
    config = container.get(interface=Config)
    return TapRestClient(
        rest_host=config.tap_host,
        macaroon_path=config.tap_macaroon_path,
        tls_cert_path=config.tap_tls_cert_path,
    )
