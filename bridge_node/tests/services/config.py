import dotenv

from .. import compose

assert compose.ENV_FILE.exists(), f"Missing {compose.ENV_FILE}"

CONFIG = dotenv.dotenv_values(compose.ENV_FILE)
