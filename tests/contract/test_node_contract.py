"""The node contract suite, run here against the simulated nodes. The same suite runs
against a real node with `fsf node test`."""

import json

import pytest

from fsf_core import topics
from fsf_core.nodetest import NodeContract


def _contract(system, node: str) -> NodeContract:
    system.stop_hub()       # the hub would switch off actuators it does not want on
    return NodeContract(system.site, system.catalog, node, system.bus,
                        wait=lambda seconds: system.run(seconds=max(seconds, system.tick)))


@pytest.mark.parametrize("site, node", [("houseplants", "shelf-node"), ("microgreens", "tray-node"),
                                        ("mushrooms", "incubation-node"), ("mushrooms", "fruiting-node")])
def test_simulated_nodes_keep_the_contract(mock, site, node):
    system = mock(site)
    contract = _contract(system, node)
    checks = contract.run(actuate=True, power_cut=lambda: system.sim.node_offline(node))
    failed = [str(c) for c in checks if not c.ok]
    assert not failed, "\n".join(failed)
    names = [c.name for c in checks]
    assert names[0] == "node announces itself as online" and names[-2].startswith("last will")
    actuators = [d for d in system.site.devices.values() if d.node == node and d.cls == "actuator"]
    assert sum("switches off by itself when the lease ends" in n for n in names) == len(actuators) > 0
    assert not any(system.is_on(d.id) for d in actuators)       # nothing is left running


def test_passive_run_switches_nothing(mock):
    system = mock("houseplants")
    system.bus.log = []
    checks = _contract(system, "shelf-node").run()
    assert all(c.ok for c in checks) and len(checks) == 6       # online, four sensors, schemas
    assert not [t for t, _ in system.bus.log if t.endswith("/cmd")]


def test_a_node_that_ignores_the_lease_fails(mock):
    system = mock("houseplants")
    contract = _contract(system, "shelf-node")
    real_step = system.sim.step

    def never_expire(dt):       # a broken node: on-commands never time out
        for act in system.sim.actuators.values():
            if act.on_until is not None:
                act.on_until = system.clock.now().replace(year=2100)
        real_step(dt)

    system.sim.step = never_expire
    failed = [c.name for c in contract.run(actuate=True) if not c.ok]
    assert "pothos-pump switches off by itself when the lease ends" in failed


def test_a_silent_sensor_and_a_bad_payload_fail(mock):
    system = mock("houseplants")
    system.sim.sensor_dropout("pothos-soil")
    contract = _contract(system, "shelf-node")
    contract.state.pop("pothos-soil", None)             # forget the retained reading from before the fault
    system.bus.publish(topics.device("houseplants", "shelf-node", "room-air", "state"), json.dumps({"air_temperature": 21}))
    failed = {c.name: c.detail for c in contract.run() if not c.ok}
    assert "pothos-soil reports soil_moisture" in failed
    assert "'t' is a required property" in failed["every message matches schemas/mqtt"]


def test_unknown_node_is_an_error(mock):
    system = mock("houseplants")
    with pytest.raises(ValueError, match="no node 'attic'"):
        NodeContract(system.site, system.catalog, "attic", system.bus, wait=lambda s: None)
