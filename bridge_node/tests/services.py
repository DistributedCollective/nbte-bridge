from . import compose

assert compose.ENV_FILE.exists(), f"Missing {compose.ENV_FILE}"


class PostgresService(compose.ComposeService):
    def __init__(self, request):
        super().__init__("postgres", request=request)

    def cli(self, *args):
        pass

    def is_started(self):
        return super().is_started()
