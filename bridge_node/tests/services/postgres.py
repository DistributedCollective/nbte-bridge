from .. import compose
from .config import CONFIG

POSTGRES_PASSWORD = CONFIG["POSTGRES_PASSWORD"]


class PostgresService(compose.ComposeService):
    def __init__(self, request):
        super().__init__("postgres", request=request)
        self._dsn_from_docker = f"postgresql://postgres:{POSTGRES_PASSWORD}@localhost:5432/"
        self._dsn_outside_docker = f"postgresql://postgres:{POSTGRES_PASSWORD}@localhost:65432/"

    def cli(self, *args, dsn: str = None):
        return self.exec(
            "psql",
            "-d",
            dsn or self._dsn_from_docker,
            "-c",
            " ".join(args),
        )

    def get_db_dsn(self, db_name: str) -> str:
        return f"{self._dsn_outside_docker}{db_name}"
