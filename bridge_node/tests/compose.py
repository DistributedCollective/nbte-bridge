import os
import logging
import pathlib
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)

COMPOSE_VERBOSE = os.environ.get("COMPOSE_VERBOSE") == "1"
PROJECT_BASE_DIR = pathlib.Path(__file__).parent.parent.parent.absolute()
COMPOSE_COMMAND = ["docker", "compose"]
COMPOSE_FILE = PROJECT_BASE_DIR / "docker-compose.dev.yaml"
ENV_FILE = PROJECT_BASE_DIR / ".env"
MAX_WAIT_TIME_S = 120
VOLUMES_DIR = PROJECT_BASE_DIR / "volumes"

assert ENV_FILE.exists(), f"Missing {ENV_FILE}"


def run_compose_command(
    *args,
    check: bool = True,
    capture: bool = False,
    quiet: bool = not COMPOSE_VERBOSE,
    **extra_kwargs,
) -> subprocess.CompletedProcess:
    extra_kwargs["check"] = check
    if capture:
        extra_kwargs["capture_output"] = True
    elif quiet:
        extra_kwargs["stdout"] = subprocess.DEVNULL
        extra_kwargs["stderr"] = subprocess.DEVNULL
    compose_args = (*COMPOSE_COMMAND, "-f", str(COMPOSE_FILE), "--env-file", str(ENV_FILE))
    return subprocess.run(
        compose_args + args,
        cwd=PROJECT_BASE_DIR,
        **extra_kwargs,
    )


def run_docker_command(
    *args,
    check: bool = True,
    capture: bool = False,
    quiet: bool = not COMPOSE_VERBOSE,
    **extra_kwargs,
) -> subprocess.CompletedProcess:
    extra_kwargs["check"] = check
    if capture:
        extra_kwargs["capture_output"] = True
    elif quiet:
        extra_kwargs["stdout"] = subprocess.DEVNULL
        extra_kwargs["stderr"] = subprocess.DEVNULL
    return subprocess.run(
        ["docker"] + list(args),
        cwd=PROJECT_BASE_DIR,
        **extra_kwargs,
    )


class ComposeExecException(RuntimeError):
    def __init__(self, stderr):
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
        if self.is_started():
            if self.build:
                logger.info(
                    "Service %s already started, but starting again in case it needs re-building.",
                    self.service,
                )
            else:
                logger.info("Service %s already started.", self.service)
                return

        logger.info("Starting docker compose service %s", self.service)
        start_args = ["up", self.service, "--detach"]
        if self.build:
            start_args.append("--build")
        run_compose_command(*start_args)

        logger.info("Waiting for service %s to start", self.service)
        self.wait()
        logger.info("Service %s started.", self.service)

    def stop(self):
        logger.info("Stopping docker compose service %s", self.service)
        run_compose_command("down", "-v", self.service)
        logger.info("Stopped service %s", self.service)

    def is_started(self):
        ret = run_compose_command(
            "ps",
            "-q",
            self.service,
            check=False,
            capture=True,
        )

        if ret.returncode != 0 or not ret.stdout.strip():
            return False

        status = (
            run_docker_command(
                "inspect",
                ret.stdout.strip(),
                "--format",
                "{{if index .State.Health }}{{.State.Health.Status}}{{end}}",
                check=False,
                capture=True,
            )
            .stdout.decode("utf-8")
            .strip()
        )

        return status in ["healthy", ""]

    def wait(self):
        start_time = time.time()
        while time.time() - start_time < MAX_WAIT_TIME_S:
            if self.is_started():
                break
            logger.info("Service %s not yet started.", self.service)
            time.sleep(1)
        else:
            raise TimeoutError(f"Service {self.service} did not start in {MAX_WAIT_TIME_S} seconds")

    def exec(self, *args: Any):
        exec_args = ["exec"]
        if self.user:
            exec_args.extend(["-u", self.user])
        exec_args.append(self.service)
        exec_args.extend(str(a) for a in args)
        try:
            return run_compose_command(
                *exec_args,
                capture=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error("Error executing command %s: %s (%s)", exec_args, e, e.stderr)
            raise ComposeExecException(e.stderr) from e
