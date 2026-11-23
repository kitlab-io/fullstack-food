"""Operator commands sent over the bus: replies, limits that still apply, pause and override."""

import json
from datetime import timedelta

import pytest

from fsf_core import topics


@pytest.fixture
def send():
    """Publish a hub command and return the hub's reply."""
    counter = iter(range(1, 1000))

    def _send(system, name: str, **fields) -> dict:
        replies: list[dict] = []
        if not hasattr(system, "_replies"):
            system._replies = replies_all = []
            system.bus.subscribe(topics.hub_reply(system.site.id), lambda t, p: replies_all.append(json.loads(p)))
        command_id = f"cmd-{next(counter)}"
        system.bus.publish(topics.hub_cmd(system.site.id), {"id": command_id, "name": name, "by": "test", **fields})
        replies = [r for r in system._replies if r["id"] == command_id]
        assert len(replies) == 1, replies
        return replies[0]

    return _send


def test_water_now_doses_once_and_keeps_the_safety_limits(mock, send):
    system = mock("houseplants")
    system.run(minutes=5)

    reply = send(system, "water_now", zone="pothos-window")
    assert reply["ok"] and reply["result"] == {"device": "pothos-pump", "volume_ml": 150.0, "duration_s": 93.8}
    assert system.is_on("pothos-pump")
    (dose,) = system.events("dose", zone="pothos-window")
    assert dose["by"] == "operator" and dose["volume_ml"] == 150

    again = send(system, "water_now", zone="pothos-window")
    assert not again["ok"] and "already running" in again["error"]

    system.run(minutes=5)
    assert system.sim.actuators["pothos-pump"].delivered_ml == pytest.approx(150, abs=1)
    assert send(system, "water_now", zone="pothos-window", volume_ml=500)["error"].startswith("volume_ml must be")
    assert send(system, "water_now", zone="pothos-window")["ok"]            # 300 ml: exactly the daily cap
    system.run(minutes=5)
    capped = send(system, "water_now", zone="pothos-window", volume_ml=10)
    assert not capped["ok"] and capped["error"].startswith("blocked: max_daily_ml")
    assert system.sim.actuators["pothos-pump"].delivered_ml == pytest.approx(300, abs=1)

    rejected = system.events("command_rejected")
    assert [e["level"] for e in rejected] == ["warn"] * 3 and rejected[0]["by"] == "test"
    assert len(system.events("command")) == 2


def test_a_manual_dose_counts_towards_the_automatic_interval(mock, send):
    system = mock("houseplants")
    assert send(system, "water_now", zone="pothos-window", volume_ml=20)["ok"]
    system.sim.zones["pothos-window"].soil = {**system.sim.zones["pothos-window"].soil, "ml_per_percent": 1e9}
    system.sim.zones["pothos-window"].soil_moisture = 20.0      # stays dry whatever is poured in
    system.run(hours=12)
    assert len(system.events("dose", zone="pothos-window")) == 1
    last = system.hub.decisions[("pothos-window", "watering", "pothos-pump")]
    assert last["want"] and last["action"] == "off" and last["reason"].startswith("blocked: min_interval until")


def test_water_now_respects_the_reservoir_interlock_and_bad_requests(mock, send):
    system = mock("houseplants")
    system.sim.set_reservoir("reservoir-level", 50)     # 2.5 % of the reservoir
    system.run(minutes=2)
    assert send(system, "water_now", zone="pothos-window")["error"] == "blocked: reservoir_low"
    assert send(system, "actuator_test", device="pothos-pump")["error"] == "blocked: reservoir_low"
    assert not system.is_on("pothos-pump")
    assert send(system, "water_now", zone="greenhouse")["error"] == "unknown zone 'greenhouse'"
    assert send(system, "water_now")["error"] == "zone is required"
    assert send(system, "open_pod_bay_doors")["error"] == "unknown command 'open_pod_bay_doors'"

    mushrooms = mock("mushrooms")
    assert "no dose loop" in send(mushrooms, "water_now", zone="incubation-chamber")["error"]


def test_advance_stage_replies_over_the_bus(mock, send):
    system = mock("mushrooms")
    reply = send(system, "advance_stage", planting="oyster-1")
    assert reply["ok"] and reply["result"] == {"stage": "fruiting"}
    assert system.hub.plantings["oyster-1"].zone == "fruiting-chamber"
    assert send(system, "advance_stage", planting="nope")["error"] == "unknown planting 'nope'"


def test_actuator_test_is_a_short_leased_pulse(mock, send):
    system = mock("houseplants")
    system.bus.log = []
    reply = send(system, "actuator_test", device="snake-pump", duration_s=4)
    assert reply["ok"]
    assert system.is_on("snake-pump")
    (on,) = [json.loads(p) for t, p in system.bus.log if t.endswith("snake-pump/cmd")]
    assert on["name"] == "on" and on["duration_s"] == 4

    assert "already on" in send(system, "actuator_test", device="snake-pump")["error"]
    system.run(minutes=2)
    assert not system.is_on("snake-pump")
    assert system.sim.actuators["snake-pump"].on_seconds == pytest.approx(4)
    assert [e["device"] for e in system.events("actuator_test")] == ["snake-pump"]
    assert not system.events("dose")                    # a test pulse is not a watering

    assert "at most 10" in send(system, "actuator_test", device="snake-pump", duration_s=60)["error"]
    assert "not an actuator" in send(system, "actuator_test", device="snake-soil")["error"]
    system.sim.node_offline("shelf-node")
    assert send(system, "actuator_test", device="snake-pump")["error"] == "blocked: node shelf-node is offline"


def test_pause_switches_everything_off_until_resumed(mock, send):
    system = mock("mushrooms")
    assert system.run(hours=3, until=lambda: system.is_on("inc-heater"))

    assert send(system, "pause_zone", zone="incubation-chamber")["ok"]
    assert not system.is_on("inc-heater")
    system.run(hours=2)
    assert system.sim.actuators["inc-heater"].log[-1][1] is False
    assert not system.is_on("inc-heater")
    assert system.status("incubation-chamber") == "paused"
    assert system.led("incubation-chamber")["status"] == "paused"
    assert system.hub.decisions[("incubation-chamber", "heat", "inc-heater")]["reason"] == "paused"

    assert send(system, "resume_zone", zone="incubation-chamber")["ok"]
    assert system.run(hours=1, until=lambda: system.is_on("inc-heater"))
    assert "paused" not in system.active("incubation-chamber")
    assert "not paused" in send(system, "resume_zone", zone="incubation-chamber")["error"]


def test_a_timed_pause_resumes_by_itself_and_survives_a_restart(mock, send, tmp_path):
    system = mock("mushrooms", db_path=str(tmp_path / "hub.db"))
    paused_at = system.clock.now()
    assert send(system, "pause_zone", zone="incubation-chamber", duration="2h")["ok"]
    system.run(minutes=30)
    system.stop_hub()
    system.start_hub()
    system.run(minutes=30)
    assert system.status("incubation-chamber") == "paused" and not system.is_on("inc-heater")

    system.run(hours=1, minutes=10)
    (resumed,) = system.events("zone_resumed")
    assert resumed["reason"] == "expired" and resumed["t"] == paused_at + timedelta(hours=2)
    assert system.run(hours=1, until=lambda: system.is_on("inc-heater"))


def test_pausing_stops_a_dose_in_progress(mock, send):
    system = mock("houseplants")
    assert send(system, "water_now", zone="pothos-window")["ok"]
    assert send(system, "pause_zone", zone="pothos-window")["ok"]
    assert not system.is_on("pothos-pump")
    assert "is paused" in send(system, "water_now", zone="pothos-window")["error"]


def test_override_changes_the_target_until_it_expires(mock, send):
    system = mock("mushrooms")
    system.run(hours=1)
    key = ("incubation-chamber", "heat", "inc-heater")
    assert system.hub.decisions[key]["inputs"]["target"] == 24

    too_high = send(system, "set_override", zone="incubation-chamber", quantity="air_temperature", target=30, duration="4h")
    assert "inconsistent band" in too_high["error"]
    assert "no target" in send(system, "set_override", zone="incubation-chamber", quantity="co2", max=900, duration="1h")["error"]

    set_at = system.clock.now()
    reply = send(system, "set_override", zone="incubation-chamber", quantity="air_temperature", target=26, duration="4h")
    assert reply["ok"] and reply["result"]["band"] == {"min": 21, "target": 26.0, "max": 27}
    system.run(hours=3)
    assert system.hub.decisions[key]["inputs"]["target"] == 26
    assert system.sim.zones["incubation-chamber"].air_temperature > 24.8

    system.run(hours=1, minutes=5)
    (cleared,) = system.events("override_cleared")
    assert cleared["reason"] == "expired" and cleared["t"] == set_at + timedelta(hours=4)
    assert system.hub.decisions[key]["inputs"]["target"] == 24


def test_override_is_dropped_when_the_stage_advances(mock, send):
    system = mock("mushrooms")
    assert send(system, "set_override", zone="incubation-chamber", quantity="air_temperature", target=25, duration="2d")["ok"]
    assert send(system, "advance_stage", planting="oyster-1")["ok"]
    assert system.hub.overrides == {}
    assert system.events("override_cleared")[0]["reason"] == "stage_advanced"


def test_hub_state_is_retained_for_late_subscribers(mock, send):
    system = mock("mushrooms")
    assert system.run(hours=3, until=lambda: system.is_on("inc-heater"))
    send(system, "pause_zone", zone="fruiting-chamber")
    send(system, "set_override", zone="incubation-chamber", quantity="air_temperature", min=20, duration="1h")
    system.run(minutes=1)

    seen: list[dict] = []
    system.bus.subscribe(topics.hub_state("mushrooms"), lambda t, p: seen.append(json.loads(p)))
    (state,) = seen                                     # delivered at once because it is retained
    assert state["plantings"]["oyster-1"] == {
        "zone": "incubation-chamber", "recipe": "blue-oyster.standard", "stage": "incubation", "stage_index": 0,
        "stage_started_at": system.hub.started_at.isoformat(), "ready": False}
    assert state["actuators"]["inc-heater"]["on"] and state["actuators"]["inc-heater"]["lease_until"]
    assert state["actuators"]["fr-fan"] == {"on": False, "level": None, "lease_until": None, "busy_until": None,
                                            "locked_until": None}
    assert state["paused"] == {"fruiting-chamber": None}
    assert state["overrides"]["incubation-chamber"]["air_temperature"]["min"] == 20
    assert state["version"] and state["tick_ms"] >= 0
