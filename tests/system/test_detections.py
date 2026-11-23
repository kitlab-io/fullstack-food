"""Faults the hub notices although every reading may be inside its band (installation plan I5).

Each test injects one fault into the simulator, checks that the right status appears with
an event naming the culprit, then removes the fault and checks that the status clears.
"""

import pytest

from fsf_core import topics


def detections(system, cleared: bool = False) -> list[tuple[str, str]]:
    kind = "detection_cleared" if cleared else "detection"
    return [(e["status"], e["subject"]) for e in system.events(kind)]


def test_a_working_heater_fighting_cold_air_is_not_a_false_alarm(mock):
    system = mock("mushrooms")
    system.run(days=2)
    assert not system.events("detection")
    assert system.status("incubation-chamber") == "ok"


def test_an_actuator_that_does_not_acknowledge_is_noticed(mock):
    system = mock("mushrooms")
    system.sim.actuator_ignores("inc-heater")           # e.g. a mains load with no driver behind it
    system.run(minutes=3)
    assert system.status("incubation-chamber") == "actuator_fault"
    (event,) = [e for e in system.events("detection") if e["status"] == "actuator_fault"]
    assert event["subject"] == "inc-heater" and "did not acknowledge a command within 60 s" in event["detail"]
    assert system.hub.store.commands(device="inc-heater", unacked=True)

    system.sim.actuator_ignores("inc-heater", False)    # the fix: reconnect it
    system.run(minutes=5)
    assert "actuator_fault" not in system.active("incubation-chamber")
    assert system.is_on("inc-heater")


def test_an_impossible_reading_is_flagged_and_not_used(mock):
    system = mock("mushrooms")
    system.run(hours=2)
    system.sim.sensor_stuck("inc-air", "air_temperature", -127.0)   # what a disconnected probe often reports
    system.run(minutes=20)
    assert "sensor_fault" in system.active("incubation-chamber") and "too_cold" not in system.active("incubation-chamber")
    assert not system.is_on("inc-heater")               # fail safe: a reading that cannot be real heats nothing
    assert system.hub.decisions[("incubation-chamber", "heat", "inc-heater")]["reason"] == "fail-safe: reading stale"
    assert system.events("detection")[-1]["detail"] == "inc-air reports air_temperature = -127, which cannot be real"

    system.sim.sensor_stuck("inc-air", "air_temperature", None)
    system.run(minutes=5)
    assert "sensor_fault" not in system.active("incubation-chamber")


def test_a_reservoir_that_loses_water_without_watering_is_noticed(mock):
    system = mock("houseplants")
    system.run(hours=1)
    full = system.sim.reservoirs["reservoir-level"]["volume_ml"]
    for _ in range(8):                                  # a slow leak: 1.5 % of the reservoir every half hour
        system.sim.set_reservoir("reservoir-level", system.sim.reservoirs["reservoir-level"]["volume_ml"] - 0.015 * full)
        system.run(minutes=30)
    for zone in ("pothos-window", "snake-shelf"):       # both pots draw from it
        assert system.status(zone) == "water_mismatch", zone
    event = system.events("detection")[-1]
    assert event["subject"] == "reservoir-level" and "with no watering" in event["detail"]
    assert not system.events("dose")

    system.run(hours=13)                                # the fix: stop the leak. The level holds, so it clears.
    assert system.status("pothos-window") == "ok" and ("water_mismatch", "reservoir-level") in detections(system, cleared=True)


def test_one_dropout_and_a_hub_restart_are_not_instability(mock, tmp_path):
    system = mock("mushrooms", db_path=str(tmp_path / "hub.db"))
    system.sim.node_offline("fruiting-node")
    system.run(minutes=5)
    system.sim.node_offline("fruiting-node", False)
    for _ in range(4):
        system.stop_hub()
        system.start_hub()
        system.run(minutes=2)
    assert not system.events("detection")


def test_every_detection_status_is_in_the_theme_with_a_meaning(mock):
    system = mock("houseplants")
    theme = system.site.theme
    for status in ("no_effect", "actuator_fault", "sensor_fault", "water_mismatch", "node_unstable"):
        assert status in theme["priority"] and theme["statuses"][status]["meaning"]
    assert theme["priority"].index("reservoir_low") < theme["priority"].index("water_mismatch")


def test_detection_thresholds_come_from_the_site_file(mock):
    system = mock("mushrooms")
    system.stop_hub()
    system.site.detection["ack_within"] = 600.0
    system.start_hub()
    system.sim.actuator_ignores("inc-heater")
    system.run(minutes=8)
    assert "actuator_fault" not in system.active("incubation-chamber")
    system.run(minutes=5)
    assert "actuator_fault" in system.active("incubation-chamber")
    assert topics.ROOT == "fsf"
