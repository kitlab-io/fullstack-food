"""The dashboard API, served from a mock system's database and in-memory bus."""

import json
from datetime import timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from fsf_web import Live, create_app  # noqa: E402
from fsf_web.auth import Auth  # noqa: E402


def test_overview_lists_zones_with_problems_first(served):
    system, client = served("houseplants")
    system.sim.zones["snake-shelf"].soil_moisture = 5.0        # far too dry for long enough to show
    system.run(hours=2)
    body = client.get("/api/zones").json()
    assert [z["id"] for z in body["zones"]] == ["snake-shelf", "pothos-window"]
    snake, pothos = body["zones"]
    assert snake["status"] == "needs_water" and pothos["status"] == "ok"
    assert body["now"] == system.clock.now().isoformat() and body["hub"]["version"]

    assert snake["planting"]["id"] == "snake-1" and snake["planting"]["species"] == "Snake plant"
    assert snake["planting"]["day"] == 1 and snake["planting"]["stage"] == "steady"
    soil = next(r for r in snake["readings"] if r["quantity"] == "soil_moisture")
    assert soil["value"] < soil["band"]["min"] and soil["unit"] == "percent" and soil["age_s"] <= 60
    level = next(r for r in snake["readings"] if r["quantity"] == "water_level")
    assert level["band"] is None and level["value"] > 50
    assert snake["nodes"] == [{"id": "shelf-node", "online": True}]


def test_staged_planting_shows_stage_progress_and_readiness(served):
    system, client = served("mushrooms")
    system.run(days=14, minutes=1)
    zones = {z["id"]: z for z in client.get("/api/zones").json()["zones"]}
    planting = zones["incubation-chamber"]["planting"]
    assert planting["stage"] == "incubation" and planting["stages"] == ["incubation", "fruiting", "harvest"]
    assert planting["day"] == 15 and planting["typical_days"] == 14 and planting["due_in_s"] <= 0
    assert planting["ready"] and planting["hint"] == "substrate fully colonised"
    assert zones["incubation-chamber"]["status"] == "stage_ready"
    assert zones["fruiting-chamber"]["planting"] is None and zones["fruiting-chamber"]["status"] == "idle"


def test_zone_detail_explains_itself(served):
    system, client = served("mushrooms")
    system.run(hours=3)
    system.hub.pause_zone("fruiting-chamber")
    system.hub.set_override("incubation-chamber", "air_temperature", "2h", target=25)
    system.run(minutes=1)
    system.refresh()

    zone = client.get("/api/zones/incubation-chamber").json()
    (heat,) = zone["decisions"]
    assert heat["loop"] == "heat" and heat["device"] == "inc-heater" and heat["reason"].startswith(("want", "blocked"))
    assert heat["inputs"]["target"] == 25
    temperature = next(r for r in zone["readings"] if r["quantity"] == "air_temperature")
    assert temperature["band"] == {"min": 21, "target": 25.0, "max": 27, "overridden": True}
    assert zone["stage_history"][0]["planting"] == "oyster-1"
    assert zone["actuators"][0]["id"] == "inc-heater" and "lease_until" in zone["actuators"][0]
    assert zone["led"]["zone"] == "incubation-chamber" and zone["led"]["status"] == zone["status"]

    paused = client.get("/api/zones/fruiting-chamber").json()
    assert paused["paused"] and paused["status"] == "paused" and paused["decisions"] == []
    assert client.get("/api/zones/greenhouse").status_code == 404


def test_series_picks_raw_or_rollups_by_span(served):
    system, client = served("mushrooms", tick=60)
    start = system.clock.now()
    system.run(days=5, hours=2, minutes=30)
    system.refresh()
    now = system.clock.now()
    url = "/api/zones/incubation-chamber/series"

    def ask(span: timedelta, **extra) -> dict:
        return client.get(url, params={"quantity": "air_temperature", "from": (now - span).isoformat(), **extra}).json()

    six_hours = ask(timedelta(hours=6))
    assert six_hours["resolution"] == "raw" and six_hours["min"] is None and six_hours["device"] == "inc-air"
    assert len(six_hours["t"]) == 360 and six_hours["unit"] == "degC"
    assert six_hours["t"] == sorted(six_hours["t"]) and six_hours["t"][-1] <= now.timestamp()

    day = ask(timedelta(hours=24))
    assert day["resolution"] == "5m" and len(day["t"]) == 288
    assert all(lo <= mean <= hi for lo, mean, hi in zip(day["min"], day["mean"], day["max"]))
    assert day["t"][-1] >= now.timestamp() - 300          # the unfinished hour is there too, from raw samples

    whole = ask(now - start)
    assert whole["resolution"] == "1h" and len(whole["t"]) == 5 * 24 + 3
    assert whole["t"][0] == start.timestamp()
    assert 13 < whole["mean"][0] < 19 and 22 < whole["mean"][-1] < 26      # cold start, then held near 24

    assert ask(timedelta(hours=24), resolution="1h")["resolution"] == "1h"
    assert client.get(url, params={"quantity": "co2"}).status_code == 404
    assert client.get(url, params={"quantity": "air_temperature", "from": "yesterday"}).status_code == 422
    assert client.get(url, params={"quantity": "air_temperature", "resolution": "1s"}).status_code == 422


def test_actuator_history_merges_lease_renewals_into_on_intervals(served):
    system, client = served("mushrooms")
    system.run(hours=6)
    system.refresh()
    body = client.get("/api/zones/incubation-chamber/actuators", params={
        "from": (system.clock.now() - timedelta(hours=6)).isoformat()}).json()
    (heater,) = body["actuators"]
    simulated = system.sim.actuators["inc-heater"]
    switched_on = [t for t, on in simulated.log if on]
    assert len(heater["intervals"]) == len(switched_on) >= 2
    assert heater["intervals"][0][0] == switched_on[0].timestamp()
    assert heater["on_s"] == pytest.approx(simulated.on_seconds, abs=60 * len(switched_on))
    assert all(a < b for a, b in heater["intervals"])


def test_actuator_history_includes_doses(served):
    system, client = served("houseplants")
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.run(hours=3)
    system.refresh()
    (pump,) = client.get("/api/zones/pothos-window/actuators").json()["actuators"]
    assert [d["volume_ml"] for d in pump["doses"]] == [150] and pump["doses"][0]["by"] == "trigger"
    (run,) = pump["intervals"]
    assert run[1] - run[0] == pytest.approx(93.8)


def test_devices_page_shows_nodes_parts_and_test_status(served):
    system, client = served("mushrooms")
    assert system.run(hours=3, until=lambda: system.is_on("inc-heater"))
    system.sim.node_offline("fruiting-node")
    system.refresh()
    nodes = {n["id"]: n for n in client.get("/api/devices").json()["nodes"]}
    assert nodes["incubation-node"]["online"] is True and nodes["fruiting-node"]["online"] is False
    assert nodes["fruiting-node"]["since"] == system.clock.now().isoformat()

    devices = {d["id"]: d for n in ("incubation-node", "plug-strip") for d in nodes[n]["devices"]}
    assert nodes["plug-strip"]["board"] == "tplink.kasa-hs300"
    air = devices["inc-air"]
    assert air["model_name"] == "Aosong AHT20" and air["driver_status"] == "verified"      # the simulated driver
    assert air["pins"] == {"sda": "GPIO5", "scl": "GPIO6"} and air["datasheet_checked"] is False
    assert {v["quantity"] for v in air["values"]} == {"air_temperature", "relative_humidity"}
    assert air["age_s"] <= 60 and air["zones"] == ["incubation-chamber"]
    heater = devices["inc-heater"]
    assert heater["on"] is True and heater["commanded_on"] is True and 0 < heater["lease_remaining_s"] <= 180
    assert heater["switched_on_24h"] == 1 and heater["unacked"] == 0 and heater["on_s_24h"] > 0


def test_site_description_carries_the_theme(served):
    _, client = served("microgreens")
    site = client.get("/api/site").json()
    assert site["id"] == "microgreens" and site["theme"]["priority"][0] == "offline"
    paused = site["theme"]["statuses"]["paused"]
    assert paused["color"] == [0, 0, 0, 40] and paused["effect"] == "blink_slow" and paused["label"] == "Paused"
    assert [s["id"] for s in site["plantings"][0]["stages"]] == ["germination", "blackout", "light", "harvest"]
    assert site["zones"][0]["indicator"] == {"strip": "status-strip", "leds": [0, 9]}


def test_stream_pushes_changes_as_server_sent_events(served):
    system, _ = served("mushrooms")
    stream = system.live.stream(keepalive=0.05, limit=3)
    assert next(stream) == "retry: 3000\n\n"
    assert next(stream) == ": keepalive\n\n"            # nothing has changed yet
    system.sim.node_offline("fruiting-node")
    system.run(minutes=1)
    events = [json.loads(line[len("data: "):]) for line in stream if line.startswith("data: ")]
    assert len(events) == 3 and not system.live._listeners      # the stream closed and unsubscribed
    assert events[0] == {"kind": "node", "node": "fruiting-node", "online": False,
                         "since": (system.clock.now() - timedelta(minutes=1)).isoformat()}
    assert {e["kind"] for e in events[1:]} <= {"device", "zone", "hub"}


def test_live_state_is_complete_for_a_service_started_late(served):
    system, _ = served("houseplants")
    system.run(hours=1)
    late = Live(system.site.id, system.bus, system.clock)       # subscribes after everything was published
    snap = late.snapshot()
    assert set(snap["zones"]) == {"pothos-window", "snake-shelf"} and snap["nodes"]["shelf-node"]["online"]
    assert snap["hub"]["plantings"]["pothos-1"]["stage"] == "steady"
    assert "soil_moisture" in snap["devices"]["pothos-soil"]["state"]


def test_api_never_writes_and_reports_a_missing_database(served, tmp_path):
    system, client = served("houseplants")
    writing = {route.path for route in client.app.routes if not getattr(route, "methods", {"GET"}) <= {"GET", "HEAD"}}
    # acting goes through the hub; /api/sim reaches only a simulator
    assert writing == {"/api/login", "/api/logout", "/api/commands", "/api/sim"}
    missing = TestClient(create_app(system.site, system.catalog, str(tmp_path / "nope.db"), system.live, auth=Auth(no_login=True)))
    assert missing.get("/api/zones").status_code == 200                # live state needs no database
    assert missing.get("/api/zones/pothos-window").status_code == 503
    assert missing.get("/api/devices").status_code == 200
    assert missing.get("/").json()["api"] == "/api/docs"
