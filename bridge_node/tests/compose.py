import os
import logging
import pathlib
import subprocess
import json

from typing import (
    Any,
    Optional,
)

from types import SimpleNamespace

logger = logging.getLogger(__name__)

COMPOSE_VERBOSE = os.environ.get("COMPOSE_VERBOSE") == "1"
PROJECT_BASE_DIR = pathlib.Path(__file__).parent.parent.parent.absolute()
COMPOSE_COMMAND = ["docker", "compose"]
COMPOSE_FILE = PROJECT_BASE_DIR / "docker-compose.dev.yaml"
ENV_FILE = PROJECT_BASE_DIR / "env.test"
MAX_WAIT_TIME_S = 120
VOLUMES_DIR = PROJECT_BASE_DIR / "volumes"
COMPOSE_BASE_ARGS = (*COMPOSE_COMMAND, "-f", str(COMPOSE_FILE), "--env-file", str(ENV_FILE))

assert ENV_FILE.exists(), f"Missing {ENV_FILE}"


def run_command(
    *args,
    check: bool = True,
    capture: bool = False,
    quiet: bool = not COMPOSE_VERBOSE,
    timeout: Optional[float] = None,
    **extra_kwargs,
) -> subprocess.CompletedProcess:
    extra_kwargs["check"] = check
    extra_kwargs["timeout"] = timeout
    extra_kwargs["capture_output"] = capture

    if quiet and not capture:
        extra_kwargs["stdout"] = subprocess.DEVNULL
        extra_kwargs["stderr"] = subprocess.DEVNULL

    return subprocess.run(
        COMPOSE_BASE_ARGS + args,
        cwd=PROJECT_BASE_DIR,
        **extra_kwargs,
    )


def compose_popen(*args, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(
        COMPOSE_BASE_ARGS + args,
        cwd=PROJECT_BASE_DIR,
        **kwargs,
    )


class ComposeExecException(RuntimeError):
    def __init__(self, stderr):
        if isinstance(stderr, bytes):
            stderr = stderr.decode()
        super().__init__(stderr)


class ComposeService:
    def __init__(
        self,
        service: str = None,
        *,
        user: str = None,
        build: bool = False,
        request=None,
    ):
        self.service = service
        self.user = user
        self.build = build
        if request:
            if not request.config.getoption("--keep-containers"):
                request.addfinalizer(self.stop)
            self.start()

    def start(self):
        """
        Starts the service.
        If the service is already running, it will only be started again if
        the `build` flag is set to True.
        """
        if self.is_running():
            if self.build:
                logger.info(
                    "Service %s already started, but starting again in case it needs re-building.",
                    self.service,
                )
            else:
                logger.info("Service %s already started.", self.service)
                return

        start_args = ["up", self.service, "--wait"]

        if self.build:
            start_args.append("--build")

        logger.info("Starting docker compose service %s", self.service)

        run_command(*start_args)

        logger.info("Service %s started.", self.service)

    def stop(self):
        """
        Stops the service and removes its volumes.
        """
        logger.info("Stopping docker compose service %s", self.service)

        run_command("down", "--volumes", self.service)

        logger.info("Stopped service %s", self.service)

    def is_running(self):
        """
        Checks if the service is running.
        If the service has a healthcheck, it needs to report healthy.
        """
        info = self.get_container_info()

        if info is None:
            return False

        return info.State == "running" and info.Health in ["healthy", ""]

    def get_container_info(self):
        output = (
            run_command("ps", "-a", "--format", "json", self.service, capture=True)
            .stdout.decode("utf-8")
            .strip()
        )

        if not output:
            return None

        return json.loads(output, object_hook=lambda d: SimpleNamespace(**d))

    def exec(self, *args: Any, timeout: Optional[float] = None):
        exec_args = self._get_exec_args(*args)

        try:
            result = run_command(
                *exec_args,
                capture=True,
                timeout=timeout,
            )

            return result.stdout.decode("utf-8"), result.stderr.decode("utf-8"), result.returncode

        except subprocess.CalledProcessError as e:
            logger.error("Error executing command %s: %s (%s)", exec_args, e, e.stderr)
            raise ComposeExecException(e.stderr) from e

    def exec_popen(self, *args, **kwargs) -> subprocess.Popen:
        popen_args = self._get_exec_args(*args)
        return compose_popen(*popen_args, **kwargs)

    def _get_exec_args(self, *args):
        exec_args = ["exec"]

        if self.user:
            exec_args.extend(["-u", self.user])

        exec_args.append(self.service)
        exec_args.extend(str(a) for a in args)

        return exec_args

    def copy_to_container(self, src: str | pathlib.Path, dest: str):
        run_command(
            "cp",
            str(src),
            f"{self.service}:{dest}",
            check=True,
            quiet=True,
        )
