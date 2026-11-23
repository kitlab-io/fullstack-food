"""Faults the hub notices although every reading may be inside its band (installation plan I5).

Each test injects one fault into the simulator, checks that the right status appears with
an event naming the culprit, then removes the fault and checks that the status clears.
"""

import pytest

from fsf_core import topics


def detections(system, cleared: bool = False) -> list[tuple[str, str]]:
    kind = "detection_cleared" if cleared else "detection"
    return [(e["status"], e["subject"]) for e in system.events(kind)]


def test_a_dose_that_moves_no_water_is_noticed_and_clears_after_a_good_one(mock):
    system = mock("houseplants")
    pot = system.sim.zones["pothos-window"]
    pot.soil_moisture = 20.0
    system.sim.pump_no_flow("pothos-pump")              # airlock: the pump runs dry
    system.run(hours=1, minutes=10)                     # trigger holds for an hour, then it doses
    assert len(system.events("dose", zone="pothos-window")) == 1
    assert "no_effect" not in system.active("pothos-window")        # too early to tell

    system.run(minutes=50)
    assert system.status("pothos-window") == "no_effect" and "needs_water" in system.active("pothos-window")
    assert system.led("pothos-window")["status"] == "no_effect"
    (event,) = system.events("detection")
    assert (event["status"], event["subject"], event["level"]) == ("no_effect", "pothos-window/watering", "warn")
    assert "soil_moisture did not change after the last dose" in event["detail"]
    assert system.status("snake-shelf") == "ok"

    system.sim.pump_no_flow("pothos-pump", False)       # the fix: prime the tube. The next dose proves it.
    system.run(hours=24)
    assert len(system.events("dose", zone="pothos-window")) == 2
    assert "no_effect" not in system.active("pothos-window")
    assert detections(system, cleared=True) == [("no_effect", "pothos-window/watering")]


def test_a_heater_that_runs_without_warming_is_noticed(mock):
    system = mock("mushrooms")
    system.run(hours=2)                                 # warmed up and holding
    assert system.status("incubation-chamber") == "ok"
    system.sim.actuator_weak("inc-heater", 0.0)         # element burnt out: the plug still switches
    system.sim.zones["incubation-chamber"].air_temperature = 18.0
    system.run(hours=1, minutes=30)
    assert "no_effect" not in system.active("incubation-chamber")
    system.run(hours=1)
    assert system.status("incubation-chamber") == "no_effect" and "too_cold" in system.active("incubation-chamber")
    event = system.events("detection")[-1]
    assert event["subject"] == "incubation-chamber/heat" and "inc-heater has been wanted on for 2 h" in event["detail"]

    system.sim.actuator_weak("inc-heater", None)        # the fix: replace the heater
    system.run(hours=2)
    assert system.status("incubation-chamber") == "ok"
    assert ("no_effect", "incubation-chamber/heat") in detections(system, cleared=True)


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


def test_an_offline_node_is_not_also_reported_as_a_dead_actuator(mock):
    system = mock("mushrooms")
    assert system.run(hours=3, until=lambda: system.is_on("inc-heater"))
    system.sim.node_offline("incubation-node")
    system.run(minutes=30)
    assert system.status("incubation-chamber") == "offline" and "actuator_fault" not in system.active("incubation-chamber")
    assert not system.events("detection")


def test_a_stuck_sensor_is_noticed(mock):
    system = mock("mushrooms")
    system.run(hours=2)
    system.sim.sensor_stuck("inc-air", "air_temperature", 23.4)     # frozen at a believable value
    system.run(hours=11)
    assert "sensor_fault" not in system.active("incubation-chamber")
    system.run(hours=2)
    assert system.status("incubation-chamber") == "sensor_fault"
    event = system.events("detection")[-1]
    assert event["subject"] == "inc-air/air_temperature/stuck" and "without any change for 12 h" in event["detail"]

    system.sim.sensor_stuck("inc-air", "air_temperature", None)     # the fix: reseat or replace the sensor
    system.run(minutes=5)
    assert "sensor_fault" not in system.active("incubation-chamber")


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


def test_watering_itself_is_not_a_leak(mock):
    system = mock("houseplants")
    system.sim.reservoirs["reservoir-level"]["capacity_ml"] = 1000      # small enough for one dose to show
    system.sim.set_reservoir("reservoir-level", 1000)
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.run(hours=8)
    assert system.events("dose") and not [e for e in system.events("detection") if e["status"] == "water_mismatch"]


def test_a_node_that_keeps_dropping_off_is_noticed(mock):
    system = mock("mushrooms")
    system.run(minutes=10)
    for _ in range(3):                                  # brown-outs when the fan starts, say
        system.sim.node_offline("fruiting-node")
        system.run(minutes=3)
        system.sim.node_offline("fruiting-node", False)
        system.run(minutes=5)
    assert system.status("fruiting-chamber") == "node_unstable"
    assert system.status("incubation-chamber") != "node_unstable"
    assert system.events("detection")[-1]["detail"] == "node fruiting-node went offline 3 times in 60 min"

    system.run(hours=1, minutes=5)                      # the fix: better power or signal. An hour of calm clears it.
    assert system.status("fruiting-chamber") == "idle"


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


@pytest.mark.parametrize("site", ["houseplants", "microgreens", "mushrooms"])
def test_healthy_sites_raise_no_detections_over_a_week(mock, site):
    system = mock(site, tick=120)
    system.run(days=7)
    assert not system.events("detection"), system.events("detection")
