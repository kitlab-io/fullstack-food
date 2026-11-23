"""The decision trace, the command log, event levels and the retention job."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from fsf_hub import Store


def reasons(system, zone: str, loop: str) -> list[str]:
    return [d["reason"] for d in system.hub.store.decisions(zone=zone, loop=loop)]


def test_trace_explains_a_heater_through_limit_and_stale_sensor(mock):
    system = mock("mushrooms")
    system.sim.set_ambient(air_temperature=5)       # too cold for the heater to ever reach target
    system.run(hours=2)

    trace = system.hub.store.decisions(zone="incubation-chamber", loop="heat")
    assert trace[0]["reason"] == "want on: air_temperature below target band"
    assert trace[0]["action"] == "on" and trace[0]["inputs"]["target"] == 24
    blocked = [d for d in trace if d["reason"].startswith("blocked: max_on, off until ")]
    assert blocked and all(d["want"] and d["action"] == "off" for d in blocked)
    limit = system.events("limit")[0]
    assert limit["level"] == "warn" and blocked[0]["t"] == limit["t"]
    # 30 minutes on, then held off for min_off: the trace names the minute it may switch on again
    assert blocked[0]["reason"].endswith((limit["t"] + timedelta(minutes=2)).strftime("%H:%M"))

    system.sim.sensor_dropout("inc-air")
    system.run(minutes=15)
    last = system.hub.decisions[("incubation-chamber", "heat", "inc-heater")]
    assert last["reason"] == "fail-safe: reading stale" and not last["want"] and last["action"] == "off"
    assert not system.is_on("inc-heater")


def test_trace_explains_watering_and_stores_only_changes(mock):
    system = mock("houseplants")
    pot = system.sim.zones["pothos-window"]
    system.run(hours=1)
    assert reasons(system, "pothos-window", "watering") == ["want off: trigger not met for 1h"]

    pot.soil_moisture = 20.0
    system.run(hours=2)
    pot.soil_moisture = 20.0
    system.run(hours=2)
    system.sim.set_reservoir("reservoir-level", 50)
    system.run(minutes=5)

    trace = system.hub.store.decisions(zone="pothos-window", loop="watering")
    told = [d["reason"] for d in trace]
    assert "dosed 150 ml" in told and "dose running" in told and "blocked: reservoir_low" in told
    waiting = next(d for d in trace if d["reason"].startswith("blocked: min_interval until "))
    assert waiting["want"] and waiting["action"] == "off" and waiting["inputs"]["below"] == 30
    assert waiting["inputs"]["value"] < 30
    # five hours of ticks every 30 s, but a row only when the decision changed
    assert len(trace) < 12


def test_schedule_and_duty_cycle_loops_are_traced(mock):
    system = mock("microgreens")
    system.run(days=4, hours=3)
    light = system.hub.decisions[("tray1", "lighting", "tray-light")]
    assert light["want"] and light["action"] == "on" and light["reason"].startswith("want on: schedule ")

    mushrooms = mock("mushrooms")
    mushrooms.hub.advance_stage("oyster-1")
    mushrooms.run(hours=6)
    told = {d["reason"] for d in mushrooms.hub.store.decisions(zone="fruiting-chamber") if d["device"] == "fr-fan"}
    assert any(r.startswith("want on: duty cycle ") for r in told)
    assert any(r.startswith("want off: duty cycle ") for r in told)


def test_every_command_is_stored_with_its_ack(mock):
    system = mock("mushrooms")
    system.run(hours=3)
    commands = system.hub.store.commands(device="inc-heater")
    assert {c["name"] for c in commands} == {"on", "off"}
    assert all(c["ok"] is True and c["ack_t"] is not None for c in commands)
    assert commands[0]["data"] == {"duration_s": system.site.safety["actuator_lease"]}
    assert not system.hub.store.commands(unacked=True)
    assert [c["name"] for c in system.hub.store.commands(device="status-strip")][0] == "render"


def test_a_refused_command_is_logged_as_a_warning(mock):
    system = mock("mushrooms")
    dev = system.site.devices["inc-heater"]
    system.hub._send(dev, {"name": "render"})        # not something a heater understands
    (failed,) = system.events("command_failed")
    assert failed["level"] == "warn" and failed["device"] == "inc-heater" and "actuators accept" in failed["error"]
    (stored,) = [c for c in system.hub.store.commands(device="inc-heater") if c["name"] == "render"]
    assert stored["ok"] is False


def test_events_can_be_filtered_by_level(mock):
    system = mock("mushrooms")
    system.sim.set_ambient(air_temperature=5)
    system.run(hours=2)
    kinds = {e["kind"] for e in system.hub.store.events(min_level="warn")}
    assert kinds == {"limit"}
    assert {e["level"] for e in system.hub.store.events("status_changed")} == {"info"}


# --------------------------------------------------------------------------- store

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


def test_rollups_cover_whole_hours_and_raw_readings_age_out():
    store = Store()
    for minute in range(150):                           # 08:00 .. 10:29, value = minute of the run
        store.reading(T0 + timedelta(minutes=minute, seconds=7.5), "probe", "air_temperature", float(minute))
    now = T0 + timedelta(minutes=150)
    store.retain(now, raw_readings=3600, decision_trace=3600)

    hourly = store.rollups("probe", "air_temperature", 3600)
    assert [(r["t"], r["min"], r["mean"], r["max"], r["n"]) for r in hourly] == [
        (T0, 0.0, 29.5, 59.0, 60), (T0 + timedelta(hours=1), 60.0, 89.5, 119.0, 60)]
    five = store.rollups("probe", "air_temperature", 300)
    assert len(five) == 24 and five[0]["mean"] == 2.0 and five[-1]["t"] == T0 + timedelta(minutes=115)
    # raw data: everything older than an hour is gone, the unfinished hour is untouched
    raw = store.readings("probe", "air_temperature")
    assert raw[0][0] == T0 + timedelta(minutes=90, seconds=7.5) and len(raw) == 60

    store.retain(now + timedelta(minutes=5), raw_readings=3600, decision_trace=3600)     # same hour: nothing new
    assert store.rollups("probe", "air_temperature", 3600) == hourly
    store.retain(now + timedelta(hours=1), raw_readings=3600, decision_trace=3600)
    assert len(store.rollups("probe", "air_temperature", 3600)) == 3
    assert store.rollups("probe", "air_temperature", 3600)[-1]["n"] == 30


def test_raw_readings_are_never_deleted_before_they_are_rolled_up():
    store = Store()
    store.reading(T0 + timedelta(minutes=50), "probe", "co2", 800.0)
    store.retain(T0 + timedelta(minutes=55), raw_readings=60, decision_trace=60)
    assert len(store.readings("probe", "co2")) == 1     # its hour is not complete yet
    store.retain(T0 + timedelta(minutes=65), raw_readings=60, decision_trace=60)
    assert not store.readings("probe", "co2") and store.rollups("probe", "co2", 3600)[0]["mean"] == 800.0


def test_old_trace_and_commands_age_out_but_events_stay():
    store = Store()
    store.decision(T0, "z", "heat", "heater", True, "on", "want on", {})
    store.command(T0, "c1", "heater", "on", {"duration_s": 180})
    store.event(T0, "dose", zone="z", volume_ml=10)
    store.decision(T0 + timedelta(days=2), "z", "heat", "heater", False, "off", "want off", {})
    store.retain(T0 + timedelta(days=2, hours=1), raw_readings=86400, decision_trace=86400)
    assert [d["reason"] for d in store.decisions()] == ["want off"]
    assert not store.commands() and len(store.events()) == 1


def test_a_database_from_before_event_levels_still_opens(tmp_path):
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, t TEXT NOT NULL, kind TEXT NOT NULL, zone TEXT, "
               "planting TEXT, data TEXT NOT NULL)")
    db.execute("INSERT INTO events (t, kind, zone, planting, data) VALUES (?, 'dose', 'z', NULL, '{\"volume_ml\": 5}')",
               (T0.isoformat(),))
    db.commit()
    db.close()
    store = Store(path)
    store.event(T0, "limit", device="heater")
    assert [(e["kind"], e["level"]) for e in store.events()] == [("dose", "info"), ("limit", "warn")]
    with pytest.raises(ValueError):
        store.event(T0, "dose", level="loud")
    store.close()


def test_database_stays_bounded_over_a_sixty_day_run(mock):
    """With the default retention (30 days raw, 14 days trace) the detailed tables stop growing."""
    system = mock("houseplants", record_readings=True, tick=300)    # coarse ticks keep sixty days fast
    system.run(days=45)
    at_45 = system.hub.store.counts()
    system.run(days=15)
    at_60 = system.hub.store.counts()

    per_day = at_45["readings"] / 30
    assert at_60["readings"] == pytest.approx(at_45["readings"], abs=per_day / 12)   # a 30-day window either way
    assert at_60["commands"] == pytest.approx(at_45["commands"], rel=0.25)
    assert at_60["decisions"] == pytest.approx(at_45["decisions"], rel=0.25, abs=20)
    assert at_60["rollups"] > at_45["rollups"]          # rollups and events are kept
    oldest = system.hub.store.rollups("room-air", "air_temperature", 3600)[0]["t"]
    assert oldest == system.hub.started_at.replace(minute=0)
