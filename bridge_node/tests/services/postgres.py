from .. import compose
from .config import CONFIG

POSTGRES_PASSWORD = CONFIG["POSTGRES_PASSWORD"]


class PostgresService(compose.ComposeService):
    dsn_from_docker: str
    dsn_outside_docker: str

    def __init__(self, request):
        super().__init__("postgres", request=request)
        self.dsn_from_docker = f"postgresql://postgres:{POSTGRES_PASSWORD}@localhost:5432/"
        self.dsn_outside_docker = f"postgresql://postgres:{POSTGRES_PASSWORD}@localhost:65432/"

    def cli(self, *args, dsn: str = None):
        return self.exec(
            "psql",
            "-d",
            dsn or self.dsn_from_docker,
            "-c",
            " ".join(args),
        )
