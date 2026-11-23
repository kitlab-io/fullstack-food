"""Dashboard plan D5: the simulator announces itself and is controlled over the bus."""

import json

import pytest
from jsonschema import Draft202012Validator

from fsf_core import find_repo_root, topics


def send(system, **command) -> dict:
    system.bus.publish(topics.sim_cmd(system.site.id), command)
    return json.loads(system.bus._retained[topics.sim_state(system.site.id)])


def test_simulator_announces_itself_with_a_retained_state(mock):
    system = mock("mushrooms")
    state = json.loads(system.bus._retained["fsf/mushrooms/sim/state"])
    schema = json.loads((find_repo_root() / "schemas/mqtt/sim_state.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(state))
    assert state["paused"] is False and state["faults"] == {
        "dropouts": [], "stuck": [], "offline_nodes": [], "no_flow": [], "ignoring": [], "weak": {}}


def test_faults_can_be_injected_and_removed_over_the_bus(mock):
    system = mock("mushrooms")
    system.run(hours=1)
    state = send(system, name="sensor_dropout", device="inc-air")
    assert state["faults"]["dropouts"] == ["inc-air"]
    send(system, name="node_offline", node="fruiting-node")
    send(system, name="sensor_stuck", device="fr-climate", quantity="co2", value=5000)
    send(system, name="actuator_ignores", device="inc-heater")
    state = send(system, name="actuator_weak", device="fr-fan", fraction=0)
    assert state["faults"]["offline_nodes"] == ["fruiting-node"] and state["faults"]["weak"] == {"fr-fan": 0}
    assert state["faults"]["stuck"] == [{"device": "fr-climate", "quantity": "co2", "value": 5000}]

    system.run(minutes=30)
    assert system.status("incubation-chamber") == "sensor_stale" and system.status("fruiting-chamber") == "offline"

    state = send(system, name="clear_faults")
    assert not any(state["faults"].values())
    system.run(minutes=10)
    assert "sensor_stale" not in system.active("incubation-chamber") and system.status("fruiting-chamber") == "idle"


def test_room_and_reservoir_can_be_changed(mock):
    system = mock("houseplants")
    state = send(system, name="set_ambient", air_temperature=31, relative_humidity=20)
    assert state["ambient"] == {"air_temperature": 31, "relative_humidity": 20}
    send(system, name="set_reservoir", device="reservoir-level", percent=4)
    system.run(hours=1)
    assert system.sim.zones["pothos-window"].air_temperature == pytest.approx(31, abs=0.5)
    assert "reservoir_low" in system.active("pothos-window") and "too_hot" in system.active("pothos-window")


def test_speed_and_pause_are_kept_for_the_run_loop(mock):
    system = mock("houseplants")
    assert send(system, name="set_speed", speed=600)["speed"] == 600 and system.sim.speed == 600
    assert send(system, name="pause")["paused"] is True and system.sim.paused
    assert send(system, name="resume")["paused"] is False
    assert send(system, name="set_speed", speed=1e9)["speed"] == 3600       # clamped


def test_bad_simulator_commands_are_ignored(mock):
    system = mock("houseplants")
    before = system.sim.state()["faults"]
    for bad in ({"name": "sensor_dropout", "device": "toaster"}, {"name": "set_speed"}, {"name": "node_offline", "node": "attic"},
                {"name": "explode"}, "not an object"):
        system.bus.publish(topics.sim_cmd("houseplants"), bad)
    system.bus.publish(topics.sim_cmd("houseplants"), b"\xff\xfe")
    assert system.sim.state()["faults"] == before and system.sim.speed == 1.0


def test_dashboard_relays_simulator_commands_and_knows_when_there_is_none(mock, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from fsf_core import InMemoryBus
    from fsf_web import Live, create_app
    from fsf_web.auth import Auth

    system = mock("mushrooms", db_path=str(tmp_path / "hub.db"))
    live = Live(system.site.id, system.bus, system.clock)
    client = TestClient(create_app(system.site, system.catalog, system.db_path, live, auth=Auth(no_login=True)))
    assert client.get("/api/sim").json()["present"] is True
    assert client.post("/api/sim", json={"name": "sensor_dropout", "device": "inc-air"}).json() == {"sent": True}
    assert client.get("/api/sim").json()["faults"]["dropouts"] == ["inc-air"]
    assert client.post("/api/sim", json={"name": "sensor_stuck", "device": "inc-air"}).status_code == 422
    assert client.post("/api/sim", json={"name": "set_speed", "speed": 0}).status_code == 422
    recent = [m for m in client.get("/api/mqtt/recent", params={"topic": "/sim/"}).json()["messages"]]
    assert {m["schema"] for m in recent} == {"sim_command", "sim_state"} and not any(m["errors"] for m in recent)

    locked = TestClient(create_app(system.site, system.catalog, system.db_path, live, auth=Auth()))
    assert locked.post("/api/sim", json={"name": "pause"}).status_code == 401

    real = Live(system.site.id, InMemoryBus(), system.clock)            # a site with no simulator on its bus
    hardware = TestClient(create_app(system.site, system.catalog, system.db_path, real, auth=Auth(no_login=True)))
    assert hardware.get("/api/sim").json()["present"] is False
    assert hardware.post("/api/sim", json={"name": "pause"}).status_code == 409
