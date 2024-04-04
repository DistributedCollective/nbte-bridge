import os
import logging
import pathlib
import subprocess
import time
import json

from typing import (
    Any,
    Optional,
)

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


def run_compose_command(
    *args,
    check: bool = True,
    capture: bool = False,
    quiet: bool = not COMPOSE_VERBOSE,
    timeout: Optional[float] = None,
    **extra_kwargs,
) -> subprocess.CompletedProcess:
    extra_kwargs["check"] = check
    if capture:
        # TODO: capture should capture just stdout, not stderr
        extra_kwargs["capture_output"] = True
    elif quiet:
        extra_kwargs["stdout"] = subprocess.DEVNULL
        extra_kwargs["stderr"] = subprocess.DEVNULL
    if timeout:
        extra_kwargs["timeout"] = timeout
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
        info = self.get_container_info()

        if info is None:
            return False

        return info["State"] == "running" and info["Health"] in ["healthy", ""]

    def get_container_info(self):
        stdout = (
            run_compose_command(
                "ps",
                "-a",
                "--format",
                "json",
                self.service,
                capture=True,
            )
            .stdout.decode("utf-8")
            .strip()
        )

        if not stdout:
            return None

        return json.loads(stdout)

    def wait(self):
        start_time = time.time()
        while time.time() - start_time < MAX_WAIT_TIME_S:
            if self.is_started():
                break
            logger.info("Service %s not yet started.", self.service)
            time.sleep(1)
        else:
            raise TimeoutError(f"Service {self.service} did not start in {MAX_WAIT_TIME_S} seconds")

    def exec(self, *args: Any, timeout: Optional[float] = None):
        exec_args = self._get_exec_args(*args)
        try:
            return run_compose_command(
                *exec_args,
                capture=True,
                timeout=timeout,
            )
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
        run_compose_command(
            "cp",
            str(src),
            f"{self.service}:{dest}",
            check=True,
            quiet=True,
        )
