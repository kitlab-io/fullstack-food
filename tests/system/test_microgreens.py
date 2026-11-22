"""Scenario: grow a tray of microgreens with automatic watering and a grow light."""

from datetime import timedelta


def test_full_grow_from_sowing_to_harvest(mock):
    system = mock("microgreens")
    start = system.clock.now()
    tray = system.sim.zones["tray1"]
    samples = []        # (stage, hour, light on, soil moisture) at every tick

    def sample():
        status = system.hub.zone_status["tray1"]
        samples.append((status["stage"], system.clock.now().hour, system.is_on("tray-light"), tray.soil_moisture))

    system.run(days=9, hours=1, each_tick=sample)

    # Stages advance on the recipe's schedule: 2 d germination, 2 d blackout, 5 d light.
    advances = system.events("stage_advanced", zone="tray1")
    assert [(e["from_stage"], e["to_stage"], e["by"]) for e in advances] == [
        ("germination", "blackout", "elapsed"), ("blackout", "light", "elapsed"), ("light", "harvest", "elapsed")]
    assert [e["t"] - start for e in advances] == [timedelta(days=2), timedelta(days=4), timedelta(days=9)]

    # The light stays off until the light stage, then follows the 06:00-22:00 photoperiod.
    assert not any(on for stage, _, on, _ in samples if stage in ("germination", "blackout"))
    lit = [(hour, on) for stage, hour, on, _ in samples if stage == "light"]
    assert lit and all(on == (6 <= hour < 22) for hour, on in lit)

    # Watering kept the tray inside the recipe band the whole time.
    moisture = [m for _, _, _, m in samples]
    assert 50 <= min(moisture) and max(moisture) <= 90
    assert len(system.events("dose", zone="tray1")) > 10

    # Harvest is signalled with white, which the RGB-only WS2812B strip mixes from R+G+B.
    assert system.status("tray1") == "stage_ready"
    led = system.led("tray1")
    assert (led["color"], led["effect"]) == ([255, 255, 255, 0], "breathe")

    # Clearing the tray finishes the planting and switches everything off.
    assert system.hub.advance_stage("radish-1") is None
    system.run(minutes=5)
    assert system.status("tray1") == "idle"
    assert system.led("tray1")["effect"] == "off"
    assert not system.is_on("tray-light") and not system.is_on("tray-pump")
    doses_before = len(system.events("dose"))
    system.run(days=1)
    assert len(system.events("dose")) == doses_before      # an empty tray is not watered


def test_cold_room_shows_too_cold_on_the_strip(mock):
    system = mock("microgreens")
    system.run(hours=1)
    assert system.status("tray1") == "ok"

    system.sim.set_ambient(air_temperature=12)     # heating failed overnight
    system.run(minutes=20)
    assert system.status("tray1") == "too_cold"
    led = system.led("tray1")
    assert (led["status"], led["color"], led["effect"]) == ("too_cold", [0, 180, 255, 0], "solid")

    system.sim.set_ambient(air_temperature=21)
    system.run(minutes=20)
    assert system.status("tray1") == "ok"
    assert system.led_statuses("tray1") == ["ok", "too_cold", "ok"]


def test_daily_water_cap_is_never_exceeded(mock):
    system = mock("microgreens")
    system.sim.zones["tray1"].soil["evaporation_pct_per_h"] = 12.0     # e.g. a fan heater pointed at the tray
    system.run(days=3)

    doses = system.events("dose", zone="tray1")
    assert len(doses) >= 12
    for dose in doses:
        window = [d for d in doses if dose["t"] - timedelta(hours=24) < d["t"] <= dose["t"]]
        assert sum(d["volume_ml"] for d in window) <= 400
    gaps = [b["t"] - a["t"] for a, b in zip(doses, doses[1:])]
    assert all(gap >= timedelta(hours=2) for gap in gaps)
    assert system.status("tray1") == "needs_water"      # and the shortfall is visible


def test_brightness_dims_at_night(mock):
    system = mock("microgreens")
    system.sim.set_ambient(air_temperature=12)
    system.run(hours=2)                                     # 10:00, daytime
    assert system.sim.leds["status-strip"]["brightness"] == 0.5
    system.run(hours=13)                                    # 23:00, inside night hours 22-07
    assert system.sim.leds["status-strip"]["brightness"] == 0.05
