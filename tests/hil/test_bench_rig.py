"""Hardware in the loop: the node contract suite against a real bench rig, at real-time speed.

Skipped unless a rig is named:

    FSF_HIL_SITE=sites/local/bench FSF_HIL_MQTT_HOST=hub.local pytest tests/hil
    FSF_HIL_ACTUATE=1 ...      also switches every actuator for a few seconds

Stop the hub or put the rig's zones in observe mode first, or it will switch off what the
suite switches on. Nothing here has been run against hardware yet.
"""

import os
import time

import pytest

from fsf_core import Catalog, MqttBus, load_site
from fsf_core.nodetest import NodeContract

SITE = os.environ.get("FSF_HIL_SITE")
HOST = os.environ.get("FSF_HIL_MQTT_HOST")
pytestmark = pytest.mark.skipif(not (SITE and HOST), reason="set FSF_HIL_SITE and FSF_HIL_MQTT_HOST to test a bench rig")


def _nodes() -> list[str]:
    if not (SITE and HOST):
        return ["(no rig)"]
    return [n["id"] for n in load_site(SITE, Catalog.load()).raw["nodes"] if n["runtime"] != "sim"]


@pytest.fixture(scope="module")
def rig():
    catalog = Catalog.load()
    site = load_site(SITE, catalog)
    bus = MqttBus(HOST, int(os.environ.get("FSF_HIL_MQTT_PORT", "1883")), client_id=f"fsf-hil-{site.id}",
                  username=os.environ.get("FSF_MQTT_USERNAME"), password=os.environ.get("FSF_MQTT_PASSWORD"))

    def wait(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            bus.poll()
            time.sleep(0.05)
        bus.poll()

    yield site, catalog, bus, wait
    bus.close()


@pytest.mark.parametrize("node", _nodes())
def test_real_node_keeps_the_contract(rig, node):
    site, catalog, bus, wait = rig
    checks = NodeContract(site, catalog, node, bus, wait).run(actuate=os.environ.get("FSF_HIL_ACTUATE") == "1")
    failed = [str(c) for c in checks if not c.ok]
    assert not failed, "\n".join(failed)
