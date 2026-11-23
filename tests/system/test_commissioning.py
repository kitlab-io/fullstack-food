"""Observe mode, commissioning records, and the bench, calibration and zone acceptance tools."""

import json

import pytest

from fsf_core import seconds
from fsf_core.recipes import scale_stage
from fsf_hub.commissioning import Bench, Calibrate, CommissioningError, HubClient, ZoneAcceptance


class Builder:
    """Stands in for the person at the bench. `on_say` lets a test act when a prompt appears."""

    def __init__(self, confirm=True, number=0.0, on_say=None):
        self._confirm, self._number, self.on_say = confirm, number, on_say
        self.said: list[str] = []

    def say(self, text):
        self.said.append(text)
        if self.on_say:
            self.on_say(text)

    def confirm(self, question):
        return self._confirm

    def number(self, question):
        return self._number() if callable(self._number) else self._number


def tools(system):
    wait = lambda s: system.run(seconds=max(s, system.tick))    # noqa: E731
    return wait, HubClient(system.site.id, system.bus, wait, by="test")


def as_real_hardware(system):
    """Restart the hub believing the nodes are real boards, so commissioning rules apply."""
    system.stop_hub()
    for node in system.site.raw["nodes"]:
        node["runtime"] = "esphome"
    system.start_hub()


# --------------------------------------------------------------------------- observe mode

def test_observe_mode_logs_decisions_but_switches_nothing(mock):
    system = mock("mushrooms")
    assert system.run(hours=3, until=lambda: system.is_on("inc-heater"))
    assert system.hub.set_zone_mode("incubation-chamber", "observe") == {"mode": "observe"}
    assert not system.is_on("inc-heater")               # switched off for real on the way in

    system.bus.log = []
    burned = system.sim.actuators["inc-heater"].on_seconds
    system.run(hours=4)
    assert not [t for t, _ in system.bus.log if t.endswith("inc-heater/cmd")]
    assert system.sim.actuators["inc-heater"].on_seconds == burned
    assert system.sim.zones["incubation-chamber"].air_temperature < 20     # nobody is heating
    assert "observing" in system.active("incubation-chamber")
    would = system.hub.decisions[("incubation-chamber", "heat", "inc-heater")]
    assert would["want"] and would["inputs"]["observed"] is True
    state = json.loads(system.bus._retained["fsf/mushrooms/hub/state"])
    assert state["observing"] == {"incubation-chamber": "set by operator"}

    system.hub.set_zone_mode("incubation-chamber", "active")
    assert system.run(minutes=5, until=lambda: system.is_on("inc-heater"))
    assert "observed" not in system.hub.decisions[("incubation-chamber", "heat", "inc-heater")]["inputs"]


def test_observe_mode_survives_a_restart(mock, tmp_path):
    system = mock("mushrooms", db_path=str(tmp_path / "hub.db"))
    system.hub.set_zone_mode("incubation-chamber", "observe")
    system.stop_hub()
    system.start_hub()
    system.run(hours=2)
    assert system.hub.observing("incubation-chamber") == "set by operator"
    assert system.sim.actuators["inc-heater"].on_seconds == 0


def test_a_zone_with_an_untested_real_actuator_stays_in_observe(mock):
    system = mock("houseplants")
    as_real_hardware(system)
    pot = system.sim.zones["pothos-window"]
    pot.soil_moisture = 20.0
    system.run(hours=3)

    assert system.hub.observing("pothos-window") == "not bench-tested: pothos-pump"
    (pretended,) = system.events("dose", zone="pothos-window")
    assert pretended["observed"] is True
    assert system.sim.actuators["pothos-pump"].delivered_ml == 0
    with pytest.raises(ValueError, match="stays in observe until these pass a bench test: pothos-pump"):
        system.hub.set_zone_mode("pothos-window", "active")
    with pytest.raises(ValueError, match="observe mode"):
        system.hub.water_now("pothos-window")

    system.hub.commission("device", "pothos-pump", "bench", ok=False, by="test")
    assert system.hub.observing("pothos-window")
    system.hub.commission("device", "pothos-pump", "bench", ok=True, by="test", data={"note": "rotor turns"})
    assert system.hub.observing("pothos-window") is None
    assert system.hub.observing("snake-shelf") == "not bench-tested: snake-pump"

    pot.soil_moisture = 20.0
    system.run(hours=2)                     # the pretended dose does not hold back the first real one
    doses = system.events("dose", zone="pothos-window")
    assert len(doses) == 2 and "observed" not in doses[1]
    assert system.sim.actuators["pothos-pump"].delivered_ml == pytest.approx(150, abs=1)
    assert system.sim.actuators["snake-pump"].delivered_ml == 0


def test_commissioning_records_are_validated_and_kept(mock, tmp_path):
    system = mock("houseplants", db_path=str(tmp_path / "hub.db"))
    _, hub = tools(system)
    assert hub.call("commission", scope="node", subject="shelf-node", step="node_test", ok=True) == {
        "scope": "node", "subject": "shelf-node", "step": "node_test", "ok": True}
    for bad in ({"scope": "device", "subject": "toaster", "step": "bench", "ok": True},
                {"scope": "device", "subject": "pothos-pump", "step": "vibes", "ok": True},
                {"scope": "device", "subject": "pothos-pump", "step": "bench", "ok": "yes"}):
        with pytest.raises(CommissioningError, match="refused commission"):
            hub.call("commission", **bad)
    system.stop_hub()
    system.start_hub()
    (record,) = system.hub.commissioning.values()
    assert record["step"] == "node_test" and record["by"] == "test" and record["t"] <= system.clock.now()


# --------------------------------------------------------------------------- bench

def test_bench_passes_a_sensor_that_responds_to_the_stimulus(mock):
    system = mock("mushrooms")
    wait, hub = tools(system)
    chamber = system.sim.zones["incubation-chamber"]
    builder = Builder(on_say=lambda text: setattr(chamber, "relative_humidity", chamber.relative_humidity + 25))
    checks = Bench(system.site, system.catalog, "inc-air", system.bus, wait, builder, hub).run()
    assert all(c.ok for c in checks), [str(c) for c in checks]
    assert [c.name for c in checks] == ["inc-air reports continuously", "air_temperature is plausible",
                                        "relative_humidity is plausible", "inc-air responds to the stimulus"]
    assert builder.said == ["Breathe on the sensor. Expected: Humidity rises within a few seconds and falls back afterwards."]
    assert "relative_humidity went from" in checks[-1].detail
    record = system.hub.commissioning[("device", "inc-air", "bench")]
    assert record["ok"] and record["by"] == "test" and len(record["data"]["checks"]) == 4


def test_bench_fails_a_silent_or_unresponsive_sensor(mock):
    system = mock("mushrooms")
    wait, hub = tools(system)
    unmoved = Bench(system.site, system.catalog, "inc-air", system.bus, wait, Builder(), hub).run()
    assert [c.ok for c in unmoved] == [True, True, True, False]
    assert system.hub.commissioning[("device", "inc-air", "bench")]["ok"] is False

    system.sim.sensor_dropout("fr-climate")
    silent = Bench(system.site, system.catalog, "fr-climate", system.bus, wait, Builder(), hub, report_within_s=120).run()
    assert not silent[0].ok and silent[0].detail.startswith("0 report(s)")


def test_bench_pulses_an_actuator_even_in_an_observing_zone(mock):
    system = mock("houseplants")
    as_real_hardware(system)
    wait, hub = tools(system)
    assert system.hub.observing("snake-shelf")
    checks = Bench(system.site, system.catalog, "snake-pump", system.bus, wait, Builder(confirm=True), hub).run()
    assert all(c.ok for c in checks), [str(c) for c in checks]
    assert system.sim.actuators["snake-pump"].on_seconds == pytest.approx(2)
    assert system.hub.observing("snake-shelf") is None          # passing the bench test lifts observe mode

    refused = Bench(system.site, system.catalog, "pothos-pump", system.bus, wait, Builder(confirm=False), hub).run()
    assert [c.ok for c in refused] == [True, False]             # it ran, but the builder did not see water move
    assert system.hub.observing("pothos-window") == "not bench-tested: pothos-pump"
    with pytest.raises(CommissioningError, match="no device 'toaster'"):
        Bench(system.site, system.catalog, "toaster", system.bus, wait, Builder(), hub)


# --------------------------------------------------------------------------- calibration

def test_soil_probe_calibration_measures_dry_and_wet(mock):
    system = mock("houseplants")
    wait, hub = tools(system)
    pot = system.sim.zones["pothos-window"]
    pot.soil = {**pot.soil, "evaporation_pct_per_h": 0.0}

    def act(text):
        pot.soil_moisture = 0.0 if "dry air" in text else 100.0

    checks, values = Calibrate(system.site, system.catalog, "pothos-soil", system.bus, wait, Builder(on_say=act), hub).run()
    assert all(c.ok for c in checks), [str(c) for c in checks]
    assert values["dry_v"] == pytest.approx(2.6, abs=0.02) and values["wet_v"] == pytest.approx(1.2, abs=0.02)
    assert system.hub.commissioning[("device", "pothos-soil", "calibration")]["data"]["values"] == values

    same, _ = Calibrate(system.site, system.catalog, "pothos-soil", system.bus, wait, Builder(), hub).run()
    assert [c.name for c in same if not c.ok] == ["the two readings are clearly apart"]


def test_pump_calibration_turns_a_timed_run_into_a_flow_rate(mock):
    system = mock("houseplants")
    wait, hub = tools(system)
    pump = system.sim.actuators["snake-pump"]
    builder = Builder(number=lambda: round(pump.delivered_ml, 1))        # what the measuring cup shows
    checks, values = Calibrate(system.site, system.catalog, "snake-pump", system.bus, wait, builder, hub).run()
    assert all(c.ok for c in checks) and values == {"flow_ml_per_s": 1.6}


def test_led_segment_check_lights_each_zone_in_turn_and_restores_the_strip(mock):
    system = mock("houseplants")
    system.run(minutes=5)
    wait, hub = tools(system)
    showing = system.sim.leds["status-strip"]["segments"]
    lit: list[list[int]] = []
    builder = Builder()
    builder.confirm = lambda question: lit.append(system.sim.leds["status-strip"]["segments"][0]["leds"]) or True
    checks, _ = Calibrate(system.site, system.catalog, "status-strip", system.bus, wait, builder, hub).run()
    assert lit == [[0, 9], [10, 19]] and len(checks) == 2 and all(c.ok for c in checks)
    assert system.sim.leds["status-strip"]["segments"] == showing

    with pytest.raises(CommissioningError, match="needs no calibration"):
        Calibrate(system.site, system.catalog, "room-air", system.bus, wait, builder, hub).run()


# --------------------------------------------------------------------------- zone acceptance

def test_scaled_stage_shortens_times_only(catalog):
    from fsf_core import find_repo_root, load_site
    site = load_site(find_repo_root() / "sites/examples/mushrooms", catalog)
    stage = site.plantings["oyster-1"].recipe["stages"][1]
    fast = scale_stage(stage, 60)
    heat, real = fast["control"][0], stage["control"][0]
    assert seconds(heat["limits"]["max_on"]) == seconds(real["limits"]["max_on"]) / 60
    assert fast["targets"] == stage["targets"] and "advance" not in fast and "advance" in stage
    assert seconds(fast["duration"]["typical"]) == 7 * 86400 / 60
    fan = next(loop for loop in fast["control"] if loop["strategy"] == "duty_cycle")
    assert seconds(fan["every"]) < 60 and stage["control"][0]["limits"] == real["limits"]      # the original is untouched


def test_zone_acceptance_runs_the_stage_for_real_and_records_the_result(mock):
    system = mock("mushrooms")
    wait, hub = tools(system)
    with pytest.raises(CommissioningError, match="not in observe mode"):
        ZoneAcceptance(system.site, system.catalog, "incubation-chamber", system.bus, system.clock, wait, hub,
                       run_s=600, tick_s=30).run()

    system.hub.set_zone_mode("incubation-chamber", "observe")
    system.run(minutes=1)
    checks = ZoneAcceptance(system.site, system.catalog, "incubation-chamber", system.bus, system.clock, wait, hub,
                            run_s=3600, tick_s=30).run()
    assert all(c.ok for c in checks), [str(c) for c in checks]
    names = [c.name for c in checks]
    assert "loop heat switched inc-heater on" in names and "loop heat moved air_temperature up" in names
    assert "max_on limits were enforced" in names               # 30 minutes became 30 seconds
    assert not system.is_on("inc-heater")                       # left off afterwards
    record = system.hub.commissioning[("zone", "incubation-chamber", "zone_test")]
    assert record["ok"] and record["data"]["stage"] == "incubation" and record["data"]["speed"] == 60
    assert system.hub.observing("incubation-chamber")           # going active stays a person's decision
    assert not system.events("dose") and system.hub.plantings["oyster-1"].stage_index == 0


def test_zone_acceptance_catches_a_pump_that_moves_no_water(mock):
    system = mock("houseplants")
    wait, hub = tools(system)
    system.hub.set_zone_mode("pothos-window", "observe")
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.sim.pump_no_flow("pothos-pump")
    system.run(minutes=1)
    checks = ZoneAcceptance(system.site, system.catalog, "pothos-window", system.bus, system.clock, wait, hub,
                            run_s=1800, tick_s=30).run()
    failed = [c.name for c in checks if not c.ok]
    assert failed == ["loop watering moved soil_moisture up"]
    assert system.sim.actuators["pothos-pump"].on_seconds > 60  # it did run
    assert system.hub.commissioning[("zone", "pothos-window", "zone_test")]["ok"] is False
    assert system.sim.actuators["snake-pump"].on_seconds == 0   # the other zone was left alone
