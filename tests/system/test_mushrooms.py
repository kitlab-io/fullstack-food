"""Scenario: mushrooms move from a warm incubation chamber to a humid fruiting chamber."""

FRUITING_ACTUATORS = ("fr-heater", "fr-humidifier", "fr-fan", "fr-light")


def test_grow_moves_through_incubation_fruiting_and_harvest(mock):
    system = mock("mushrooms")
    incubation = system.sim.zones["incubation-chamber"]
    fruiting = system.sim.zones["fruiting-chamber"]
    assert system.status("fruiting-chamber") == "idle"

    # --- incubation: the heat mat holds the chamber in band in a 14 degC room
    system.run(hours=3)                                         # warm-up
    temps = []
    system.run(days=13, each_tick=lambda: temps.append(incubation.air_temperature))
    assert 21 <= min(temps) and max(temps) <= 27
    assert system.status("incubation-chamber") == "ok"
    assert all(system.sim.actuators[a].on_seconds == 0 for a in FRUITING_ACTUATORS)    # empty chamber stays off

    # --- after the typical 14 days the strip asks for a decision; nothing moves by itself
    system.run(days=1)
    assert system.status("incubation-chamber") == "stage_ready"
    assert system.led("incubation-chamber")["color"] == [0, 0, 0, 255]      # white channel on the RGBW strip
    assert system.hub.stage_of("oyster-1")["id"] == "incubation"

    # --- the grower moves the block and confirms: setpoints follow it to the fruiting chamber
    assert system.hub.advance_stage("oyster-1") == "fruiting"
    assert system.hub.plantings["oyster-1"].zone == "fruiting-chamber"
    system.run(minutes=5)
    assert system.status("incubation-chamber") == "idle"
    assert not system.is_on("inc-heater")

    system.run(hours=2)                                         # chamber comes up to humidity
    samples = []

    def sample():
        now = system.clock.now()
        samples.append((fruiting.air_temperature, fruiting.relative_humidity, fruiting.co2,
                        now.hour, system.is_on("fr-light"), system.hub.zone_status["fruiting-chamber"]["state"]))

    system.run(days=3, each_tick=sample)
    temps, humidity, co2, hours, lights, states = zip(*samples)
    assert 13 <= min(temps) and max(temps) <= 18
    assert max(humidity) <= 97 and min(humidity) >= 80         # brief dips during fan bursts are tolerated...
    assert sum(h >= 85 for h in humidity) / len(humidity) > 0.97   # ...but it is in band nearly always
    assert max(co2) <= 1000
    assert set(states) == {"ok"}
    assert all(on == (7 <= hour < 19) for hour, on in zip(hours, lights))
    assert system.sim.actuators["fr-light"].level == 0.3
    assert system.sim.actuators["fr-fan"].on_seconds > 0

    # --- fruiting done, harvest, clear the chamber
    system.run(days=4)
    assert system.status("fruiting-chamber") == "stage_ready"
    assert system.hub.advance_stage("oyster-1") == "harvest"
    system.run(hours=1)
    assert system.status("fruiting-chamber") == "stage_ready"  # harvest waits for the grower too
    assert system.hub.advance_stage("oyster-1") is None
    system.run(minutes=5)
    assert system.status("fruiting-chamber") == "idle"
    assert not any(system.is_on(a) for a in FRUITING_ACTUATORS)
    assert [e["to_stage"] for e in system.events("stage_advanced")] == ["fruiting", "harvest"]
    assert len(system.events("planting_finished")) == 1


def test_heater_shuts_off_when_its_temperature_sensor_goes_quiet(mock):
    system = mock("mushrooms")
    chamber = system.sim.zones["incubation-chamber"]
    system.run(hours=3)
    assert system.status("incubation-chamber") == "ok"

    system.sim.sensor_dropout("inc-air")
    system.run(minutes=15)             # stale after 10 minutes
    assert system.status("incubation-chamber") == "sensor_stale"
    assert not system.is_on("inc-heater")
    assert system.led("incubation-chamber")["effect"] == "blink"
    burned = system.sim.actuators["inc-heater"].on_seconds
    system.run(hours=3)
    assert system.sim.actuators["inc-heater"].on_seconds == burned     # it never heats blind
    assert chamber.air_temperature < 18                                 # and the chamber cools, which the status reports

    system.sim.sensor_dropout("inc-air", False)
    system.run(hours=2)
    assert system.status("incubation-chamber") == "ok"
    assert chamber.air_temperature >= 21


def test_heater_cannot_run_past_its_max_on_time(mock):
    system = mock("mushrooms")
    system.sim.sensor_stuck("inc-air", "air_temperature", 15.0)    # sensor fell off the wall: always reads cold
    system.run(hours=6)
    log = system.sim.actuators["inc-heater"].log
    runs = [(off - on).total_seconds() for (on, a), (off, b) in zip(log, log[1:]) if a and not b]
    assert runs and max(runs) <= 30 * 60 + system.tick              # recipe limit: max_on 30m
    assert any(e["reason"] == "max_on" for e in system.events("limit"))
    assert system.status("incubation-chamber") == "too_cold"       # the mismatch is visible


def test_offline_node_is_reported_and_its_actuators_fall_safe(mock):
    system = mock("mushrooms")
    assert system.run(hours=3, until=lambda: system.is_on("inc-heater"))

    system.sim.node_offline("incubation-node")
    system.run(minutes=1)
    assert system.status("incubation-chamber") == "offline"
    led = system.led("incubation-chamber")          # the strip is on the other node, so it can still show it
    assert (led["status"], led["effect"]) == ("offline", "blink_slow")
    system.run(minutes=4)
    assert not system.is_on("inc-heater")           # lease expired on the node; no command was needed
    assert system.status("fruiting-chamber") == "idle"

    system.sim.node_offline("incubation-node", False)
    system.run(hours=2)
    assert system.status("incubation-chamber") == "ok"
    assert system.sim.zones["incubation-chamber"].air_temperature >= 21
