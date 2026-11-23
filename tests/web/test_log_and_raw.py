"""Dashboard plan D3: the verbose log, the MQTT tail, raw readings and exports."""

import csv
import io
import json
import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from fsf_core import topics  # noqa: E402
from fsf_web import create_app  # noqa: E402


def test_a_stale_sensor_can_be_diagnosed_from_the_log_alone(served):
    """The D3 done-when: find out from the API what went wrong, without reading hub code."""
    system, client = served("mushrooms")
    system.run(hours=2)
    system.sim.sensor_dropout("inc-air")
    system.run(minutes=30)
    system.refresh()

    problems = client.get("/api/log", params={"level": "warn", "zone": "incubation-chamber"}).json()["rows"]
    assert [r["text"] for r in problems][-1] == "heat: inc-heater off, fail-safe: reading stale"
    assert problems[-1]["source"] == "decision" and problems[-1]["data"]["inputs"]["value"] is None

    status = client.get("/api/log", params={"group": "status", "zone": "incubation-chamber"}).json()["rows"]
    assert status[-1]["text"].endswith("-> sensor_stale") and status[-1]["level"] == "info"
    # and the devices page says which part went quiet
    nodes = client.get("/api/devices").json()["nodes"]
    air = next(d for n in nodes for d in n["devices"] if d["id"] == "inc-air")
    assert air["age_s"] >= 30 * 60


def test_log_merges_events_and_decisions_and_filters(served):
    system, client = served("houseplants")
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.run(hours=3)
    system.bus.publish(topics.hub_cmd("houseplants"), {"id": "x1", "name": "water_now", "zone": "attic", "by": "ada"})
    system.refresh()

    body = client.get("/api/log").json()
    rows = body["rows"]
    assert [r["t"] for r in rows] == sorted(r["t"] for r in rows)
    assert {"event", "decision"} == {r["source"] for r in rows} and "decision" in body["groups"]
    assert len({r["id"] for r in rows}) == len(rows)

    (dose,) = client.get("/api/log", params={"group": "dose"}).json()["rows"]
    assert dose["text"] == "pothos-pump dosed 150 ml (automatic)" and dose["zone"] == "pothos-window"
    assert dose["device"] == "pothos-pump" and dose["data"]["duration_s"] == 93.8

    (rejected,) = client.get("/api/log", params={"level": "warn"}).json()["rows"]
    assert rejected["text"] == "water_now rejected: unknown zone 'attic'" and rejected["data"]["by"] == "ada"
    assert client.get("/api/log", params={"q": "ADA"}).json()["rows"] == [rejected]

    snake = client.get("/api/log", params={"zone": "snake-shelf", "group": "decision,status"}).json()["rows"]
    assert snake and {r["zone"] for r in snake} == {"snake-shelf"} and {r["group"] for r in snake} <= {"decision", "status"}
    assert len(client.get("/api/log", params={"limit": 2}).json()["rows"]) == 2
    assert client.get("/api/log", params={"limit": 2}).json()["rows"] == rows[-2:]
    cutoff = rows[3]["t"]
    assert all(r["t"] >= cutoff for r in client.get("/api/log", params={"from": cutoff}).json()["rows"])
    assert client.get("/api/log", params={"level": "loud"}).status_code == 422


def test_log_exports_as_json_lines_and_csv(served):
    system, client = served("houseplants")
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.run(hours=3)
    system.refresh()
    expected = client.get("/api/log", params={"group": "dose,status"}).json()["rows"]

    lines = client.get("/api/log", params={"group": "dose,status", "format": "jsonl"})
    assert lines.headers["content-disposition"] == 'attachment; filename="houseplants-log.jsonl"'
    assert [json.loads(line) for line in lines.text.splitlines()] == expected

    table = list(csv.DictReader(io.StringIO(client.get("/api/log", params={"group": "dose", "format": "csv"}).text)))
    assert len(table) == 1 and table[0]["kind"] == "dose" and json.loads(table[0]["data"])["volume_ml"] == 150


def test_mqtt_tail_buffers_traffic_and_flags_payloads_that_break_the_contract(served):
    system, client = served("houseplants")
    system.run(minutes=5)
    base = "fsf/houseplants/shelf-node"
    system.bus.publish(f"{base}/room-air/state", {"air_temperature": "warm"})       # no t, and a string
    system.bus.publish(f"{base}/pothos-pump/cmd", {"id": "c1", "name": "on"})       # on without a lease
    system.bus.publish(f"{base}/status", "sleepy")
    system.bus.publish(f"{base}/snake-soil/state", b"\xff not json")

    messages = client.get("/api/mqtt/recent", params={"limit": 2000}).json()["messages"]
    assert [m["n"] for m in messages] == sorted(m["n"] for m in messages)
    assert not any("/sim/" in m["topic"] for m in messages)
    by_topic = {m["topic"]: m for m in messages}
    assert by_topic[f"{base}/room-air/state"]["errors"] == ["'t' is a required property"]
    assert by_topic[f"{base}/pothos-pump/cmd"]["errors"] == ["'duration_s' is a required property"]
    assert by_topic[f"{base}/status"]["errors"] == ["must be online or offline"]
    assert by_topic[f"{base}/snake-soil/state"]["errors"] == ["not JSON"]
    good = by_topic["fsf/houseplants/hub/state"]
    assert good["schema"] == "hub_state" and good["errors"] == [] and good["payload"]["plantings"]
    # everything the hub and the simulated nodes sent by themselves is valid
    ours = {f"{base}/room-air/state", f"{base}/pothos-pump/cmd", f"{base}/status", f"{base}/snake-soil/state"}
    assert not [m for m in messages if m["errors"] and m["topic"] not in ours]

    zone_only = client.get("/api/mqtt/recent", params={"topic": "fsf/houseplants/zone/+/status"}).json()["messages"]
    assert zone_only and {m["schema"] for m in zone_only} == {"zone_status"}
    assert client.get("/api/mqtt/recent", params={"topic": "reservoir", "limit": 1}).json()["messages"][0]["topic"].endswith(
        "reservoir-level/state")


def test_raw_stream_carries_every_message_and_the_normal_stream_none(served):
    system, _ = served("mushrooms")
    raw = system.live.stream(keepalive=0.05, limit=4, raw=True)
    plain = system.live.stream(keepalive=0.05, limit=2)
    next(raw), next(plain)
    system.run(minutes=1)
    got = [json.loads(line[6:]) for line in raw if line.startswith("data: ")]
    assert "mqtt" in {e["kind"] for e in got} and all("n" in e for e in got if e["kind"] == "mqtt")
    assert not [e for e in (json.loads(line[6:]) for line in plain if line.startswith("data: ")) if e["kind"] == "mqtt"]


def test_readings_browser_returns_raw_samples_and_csv(served):
    system, client = served("houseplants")
    system.run(hours=2)
    system.refresh()
    body = client.get("/api/readings", params={"device": "pothos-soil", "quantity": "soil_moisture"}).json()
    assert len(body["samples"]) == 120 and body["samples"][0]["t"] < body["samples"][-1]["t"]
    raw = client.get("/api/readings", params={"device": "pothos-soil", "quantity": "raw"}).json()["samples"]
    assert 1.2 < raw[0]["value"] < 2.6                  # the probe's volts, as real firmware reports them

    download = client.get("/api/readings", params={"device": "pothos-soil", "quantity": "soil_moisture", "format": "csv"})
    assert download.headers["content-disposition"] == 'attachment; filename="houseplants-pothos-soil-soil_moisture.csv"'
    rows = list(csv.reader(io.StringIO(download.text)))
    assert rows[0] == ["t", "value"] and len(rows) == 121 and float(rows[1][1]) == body["samples"][0]["value"]
    assert client.get("/api/readings", params={"device": "toaster", "quantity": "heat"}).status_code == 404


def test_diagnostics_bundle_redacts_secrets(served):
    system, client = served("houseplants")
    system.site.raw["mqtt"] = {"host": "broker.local", "password": "hunter2", "api_key": "abc"}
    system.run(hours=1)
    system.refresh()
    response = client.get("/api/export/diagnostics")
    assert "hunter2" not in response.text and "abc" not in json.dumps(response.json()["site"]["mqtt"])
    bundle = response.json()
    assert bundle["site"]["mqtt"] == {"host": "broker.local", "password": "<redacted>", "api_key": "<redacted>"}
    assert bundle["hub"]["plantings"] and bundle["log"] and bundle["database"]["events"] > 0
    assert bundle["nodes"]["shelf-node"]["online"] is True


def test_database_download_needs_developer_mode(served, tmp_path):
    system, client = served("houseplants")
    system.run(hours=1)
    system.refresh()
    assert client.get("/api/export/db").status_code == 403
    assert client.get("/api/meta").json()["developer"] is False

    developer = TestClient(create_app(system.site, system.catalog, system.db_path, system.live, developer=True))
    response = developer.get("/api/export/db")
    assert response.status_code == 200 and response.content[:15] == b"SQLite format 3"
    copy = tmp_path / "copy.db"
    copy.write_bytes(response.content)
    db = sqlite3.connect(copy)
    assert db.execute("SELECT COUNT(*) FROM readings").fetchone()[0] > 0
    db.close()


def test_devices_and_zones_show_commissioning_state(served):
    system, client = served("houseplants")
    system.hub.commission("device", "pothos-pump", "bench", ok=True, by="ada")
    system.hub.set_zone_mode("snake-shelf", "observe")
    system.run(minutes=1)
    devices = {d["id"]: d for n in client.get("/api/devices").json()["nodes"] for d in n["devices"]}
    assert devices["pothos-pump"]["commissioning"]["bench"]["ok"] is True
    assert devices["pothos-pump"]["commissioning"]["bench"]["by"] == "ada" and devices["snake-pump"]["commissioning"] == {}
    zones = {z["id"]: z for z in client.get("/api/zones").json()["zones"]}
    assert zones["snake-shelf"]["observing"] == "set by operator" and zones["pothos-window"]["observing"] is None
    assert "observing" in zones["snake-shelf"]["active"]
