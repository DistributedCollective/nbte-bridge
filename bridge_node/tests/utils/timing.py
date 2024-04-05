import logging
from contextlib import contextmanager
from time import time


logger = logging.getLogger(__name__)


@contextmanager
def measure_time(name):
    start = time()
    yield
    logger.info("%s took %.2f seconds", name, time() - start)
