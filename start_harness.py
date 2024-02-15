"""
Start docker compose harness for running integration tests quickly (with NO_START_HARNESS=1)
Might result in tests that bleed state to other tests or otherwise don't work properly.

It's not necessary to run this manually, as the integration tests start the harness by default
"""
import logging
import sys
sys.path.extend("bridge_node")
from tests.integration.fixtures.harness import IntegrationTestHarness

logging.basicConfig(level=logging.INFO)

harness = IntegrationTestHarness(verbose=True)
try:
    harness.start()
    print("Harness started, viewing logs of the federator nodes")
    harness._run_docker_compose_command("logs", "-f", "bridge-node-1", "bridge-node-2")
except KeyboardInterrupt:
    print("Stopping")
finally:
    harness.stop()

