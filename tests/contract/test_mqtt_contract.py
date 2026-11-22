"""Every message the hub and the simulated nodes exchange must match schemas/mqtt/."""

import json

from jsonschema import Draft202012Validator

from fsf_core import find_repo_root


def _validators():
    folder = find_repo_root() / "schemas" / "mqtt"
    return {p.name.split(".")[0]: Draft202012Validator(json.loads(p.read_text(encoding="utf-8")))
            for p in folder.glob("*.schema.json")}


def test_all_traffic_matches_the_contract(mock):
    system = mock("houseplants")
    system.bus.log = []
    system.sim.zones["pothos-window"].soil_moisture = 20.0      # force a watering so commands flow
    system.run(hours=3)

    validators = _validators()
    seen = {"state": 0, "command": 0, "ack": 0, "zone_status": 0, "node_status": 0}
    for topic, payload in system.bus.log:
        parts = topic.split("/")
        assert parts[0] == "fsf" and parts[1] == "houseplants", topic
        if parts[2] == "zone":
            kind = "zone_status"
        elif parts[2] == "sim":
            continue
        elif len(parts) == 4 and parts[3] == "status":
            assert payload in (b"online", b"offline")
            seen["node_status"] += 1
            continue
        else:
            kind = {"state": "state", "cmd": "command", "ack": "ack"}[parts[4]]
        errors = [e.message for e in validators[kind].iter_errors(json.loads(payload))]
        assert not errors, f"{topic}: {errors}"
        seen[kind] += 1

    assert all(count > 0 for kind, count in seen.items() if kind != "node_status"), seen
    assert system.events("dose", zone="pothos-window")


def test_actuator_commands_always_carry_a_lease(mock):
    """An on-command without a duration could leave a pump or heater running if the hub died."""
    system = mock("mushrooms")
    system.bus.log = []
    system.run(hours=2)
    on_commands = [json.loads(p) for t, p in system.bus.log if t.endswith("/cmd") and json.loads(p)["name"] == "on"]
    assert on_commands
    lease = system.site.safety["actuator_lease"]
    assert all(0 < c["duration_s"] <= lease for c in on_commands)
