"""Scenario: monitor house plants and water them from a shared reservoir."""

from datetime import timedelta


def test_reservoir_running_dry_mid_dose_stops_the_pump(mock):
    system = mock("houseplants")
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.sim.set_reservoir("reservoir-level", 540)        # just above the 10 % cut-off, less than one dose spare
    assert system.run(hours=2, until=lambda: system.is_on("pothos-pump"))
    system.run(minutes=5)
    assert not system.is_on("pothos-pump")
    stops = [e for e in system.events("interlock") if e.get("stopped")]
    assert stops and stops[0]["reason"] == "reservoir_low"
    assert system.sim.actuators["pothos-pump"].delivered_ml < 150
