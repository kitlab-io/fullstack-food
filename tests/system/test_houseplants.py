"""Scenario: monitor house plants and water them from a shared reservoir."""

from datetime import timedelta

BLUE = [0, 0, 255, 0]


def test_dry_pot_is_watered_and_the_led_recovers(mock):
    system = mock("houseplants")
    pot = system.sim.zones["pothos-window"]
    pot.soil_moisture = 20.0            # below the recipe's 25 % minimum

    system.run(minutes=10)
    assert system.status("pothos-window") == "needs_water"
    led = system.led("pothos-window")
    assert (led["status"], led["color"], led["effect"]) == ("needs_water", BLUE, "breathe")
    assert system.status("snake-shelf") == "ok"         # the other pot is unaffected

    assert system.run(hours=2, until=lambda: bool(system.events("dose", zone="pothos-window")))
    system.run(minutes=30)
    (dose,) = system.events("dose", zone="pothos-window")
    assert dose["volume_ml"] == 150
    assert abs(system.sim.actuators["pothos-pump"].delivered_ml - 150) < 3     # the pump really moved it
    assert pot.soil_moisture > 30
    assert system.status("pothos-window") == "ok"
    assert system.led_statuses("pothos-window") == ["ok", "needs_water", "ok"]
    assert not system.is_on("pothos-pump")


def test_watering_respects_minimum_interval_however_thirsty_the_pot(mock):
    system = mock("houseplants")
    pot = system.sim.zones["pothos-window"]
    pot.soil["evaporation_pct_per_h"] = 3.0     # a pot that dries far faster than the recipe allows for
    system.run(days=4)

    doses = system.events("dose", zone="pothos-window")
    assert len(doses) >= 3
    gaps = [b["t"] - a["t"] for a, b in zip(doses, doses[1:])]
    assert all(gap >= timedelta(hours=24) for gap in gaps)
    for dose in doses:      # rolling 24 h total never exceeds the recipe's daily cap
        window = [d for d in doses if dose["t"] - timedelta(hours=24) < d["t"] <= dose["t"]]
        assert sum(d["volume_ml"] for d in window) <= 300
    # Watering cannot keep up, and the strip says so instead of quietly over-watering.
    assert "needs_water" in system.led_statuses("pothos-window")


def test_empty_reservoir_blocks_the_pump_and_shows_reservoir_low(mock):
    system = mock("houseplants")
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.sim.set_reservoir("reservoir-level", 0)

    system.run(hours=4)
    assert system.events("dose") == []
    assert system.sim.actuators["pothos-pump"].on_seconds == 0
    assert system.status("pothos-window") == "reservoir_low"
    # It was full a moment ago and nothing was watered, so the hub also suspects a leak.
    assert set(system.active("pothos-window")) == {"reservoir_low", "needs_water", "water_mismatch"}
    led = system.led("pothos-window")
    assert (led["color"], led["effect"]) == (BLUE, "blink")
    # Both pots draw from this reservoir, so both report it.
    assert system.status("snake-shelf") == "reservoir_low"

    system.sim.set_reservoir("reservoir-level", 5000)       # refill
    assert system.run(hours=3, until=lambda: bool(system.events("dose", zone="pothos-window")))
    system.run(minutes=30)
    assert system.status("pothos-window") == "ok"


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


def test_cold_room_raises_a_critical_alert(mock):
    system = mock("houseplants")
    system.sim.set_ambient(air_temperature=7)      # window left open in winter
    system.run(minutes=15)
    assert system.status("pothos-window") == "critical"        # species default: below 10 degC
    assert system.led("pothos-window")["effect"] == "blink"
    assert system.status("snake-shelf") == "too_cold"          # below its 13 degC band, no critical alert defined
    assert system.led("snake-shelf")["color"] == [0, 180, 255, 0]

    system.sim.set_ambient(air_temperature=21)
    system.run(minutes=30)
    assert system.status("pothos-window") == "ok"
    assert system.status("snake-shelf") == "ok"
