"""The system must behave when the hub crashes or restarts mid-grow."""

from datetime import timedelta


def test_restarted_hub_resumes_the_same_stage_and_schedule(mock, tmp_path):
    system = mock("microgreens", db_path=str(tmp_path / "hub.db"))
    start = system.clock.now()
    system.run(days=2, hours=12)
    assert system.hub.stage_of("radish-1")["id"] == "blackout"
    doses_before = len(system.events("dose"))
    assert doses_before > 0

    system.stop_hub()
    system.run(hours=2)                     # hub is down for two hours
    system.start_hub()

    assert system.hub.stage_of("radish-1")["id"] == "blackout"
    assert system.hub.plantings["radish-1"].stage_started_at == start + timedelta(days=2)
    assert len(system.events("dose")) == doses_before          # history survived
    assert system.events("planting_started")[0]["t"] == start  # and the planting was not started twice
    assert len(system.events("planting_started")) == 1

    system.run(days=1, hours=12)            # the stage still ends 4 days after sowing, not 4 days after the restart
    (to_light,) = [e for e in system.events("stage_advanced") if e["to_stage"] == "light"]
    assert to_light["t"] == start + timedelta(days=4)
    assert system.status("tray1") == "ok"


def test_restart_does_not_bypass_the_watering_interval(mock, tmp_path):
    system = mock("houseplants", db_path=str(tmp_path / "hub.db"))
    pot = system.sim.zones["pothos-window"]
    pot.soil_moisture = 20.0
    assert system.run(hours=2, until=lambda: bool(system.events("dose", zone="pothos-window")))
    first = system.events("dose", zone="pothos-window")[0]["t"]

    system.run(minutes=10)
    pot.soil_moisture = 20.0                # still dry (say the tube popped out)
    system.stop_hub()
    system.start_hub()
    system.run(hours=12)
    assert len(system.events("dose", zone="pothos-window")) == 1       # no second dose inside 24 h

    system.run(hours=14)
    doses = system.events("dose", zone="pothos-window")
    assert len(doses) == 2 and doses[1]["t"] - first >= timedelta(hours=24)


def test_hub_restart_switches_off_an_actuator_it_no_longer_wants(mock, tmp_path):
    system = mock("microgreens", db_path=str(tmp_path / "hub.db"))
    system.run(days=4, hours=2)             # light stage, 10:00: the grow light is on
    assert system.is_on("tray-light")
    system.stop_hub()
    system.run(minutes=1)
    # While the hub is down someone swaps in a recipe override that forbids light.
    system.site.plantings["radish-1"].recipe["stages"][2]["control"] = [
        loop for loop in system.site.plantings["radish-1"].recipe["stages"][2]["control"] if loop["id"] != "lighting"]
    system.start_hub()
    system.run(minutes=1)
    assert not system.is_on("tray-light")
