"""Installation plan I5: every fault leads to a guide, and `fsf doctor` names the fix."""

import json
import zipfile

import pytest

from fsf_core import ConfigError, troubleshooting
from fsf_core.__main__ import main
from fsf_core.doctor import Doctor, redact


def test_every_status_a_zone_can_show_has_a_guide(catalog):
    doc = troubleshooting.load(catalog)
    theme = catalog.get("Theme", "default")
    assert set(doc["statuses"]) == set(theme["priority"]) - {"ok", "idle"}
    for status, guide in doc["statuses"].items():
        assert guide["causes"] and guide["checks"] and guide["clears"] and guide["doing"], status
    entry = troubleshooting.for_status(catalog, "no_effect")
    assert entry["label"] == "No effect" and entry["symptoms"][0]["symptom"] == "The pump runs but the soil stays dry"
    assert troubleshooting.for_status(catalog, "ok") is None


@pytest.mark.parametrize("fault, site, zone, hours, status", [
    (lambda sim: sim.sensor_dropout("inc-air"), "mushrooms", "incubation-chamber", 1, "sensor_stale"),
    (lambda sim: sim.node_offline("incubation-node"), "mushrooms", "incubation-chamber", 0.1, "offline"),
    (lambda sim: sim.sensor_stuck("inc-air", "air_temperature", -127.0), "mushrooms", "incubation-chamber", 0.5, "sensor_fault"),
    (lambda sim: sim.actuator_ignores("inc-heater"), "mushrooms", "incubation-chamber", 0.2, "actuator_fault"),
    (lambda sim: sim.set_reservoir("reservoir-level", 100), "houseplants", "pothos-window", 0.2, "reservoir_low"),
])
def test_an_injected_fault_leads_to_its_guide(mock, catalog, fault, site, zone, hours, status):
    system = mock(site)
    system.run(hours=1)
    fault(system.sim)
    system.run(hours=hours)
    assert system.status(zone) == status
    guide = troubleshooting.for_status(catalog, system.status(zone))
    assert guide and len(guide["checks"]) >= 2 and guide["meaning"]


def test_pages_are_generated_by_status_symptom_and_part(catalog, tmp_path, capsys):
    written = {p.name: p for p in troubleshooting.build(catalog, tmp_path)}
    statuses = set(troubleshooting.load(catalog)["statuses"])
    assert {f"status-{s}.html" for s in statuses} <= set(written)
    assert {"index.html", "symptoms.html", "parts.html", "troubleshooting.md"} <= set(written)

    page = written["status-sensor_stale.html"].read_text(encoding="utf-8")
    assert "<h1>Sensor not reporting</h1>" in page and "What the hub is doing" in page and "fail-safe" in page
    assert page.index("Likely causes") < page.index("What to check") < page.index("When it clears")
    index = written["index.html"].read_text(encoding="utf-8")
    assert index.index("status-offline.html") < index.index("status-needs_water.html")      # in the strip's priority order
    parts = written["parts.html"].read_text(encoding="utf-8")
    assert "12 V peristaltic pump" in parts and "Pump runs but no water arrives" in parts and "not yet confirmed on a bench" in parts
    text = written["troubleshooting.md"].read_text(encoding="utf-8")
    assert "### Reservoir low (`reservoir_low`)" in text and "## By symptom" in text and "http" not in text

    assert main(["docs", "troubleshooting", "--out", str(tmp_path / "again")]) == 0
    assert "status-no_effect.html" in capsys.readouterr().out


def test_a_status_without_a_guide_fails_validation(catalog, monkeypatch):
    theme = catalog.get("Theme", "default")
    monkeypatch.setitem(theme["statuses"], "on_fire", {"color": [255, 0, 0, 0], "effect": "blink"})
    theme["priority"].append("on_fire")
    try:
        with pytest.raises(ConfigError, match="no entry for status 'on_fire'"):
            troubleshooting.load(catalog)
    finally:
        theme["priority"].remove("on_fire")


def test_dashboard_serves_the_same_guides(mock, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from fsf_web import Live, create_app
    from fsf_web.auth import Auth

    system = mock("houseplants", db_path=str(tmp_path / "hub.db"))
    client = TestClient(create_app(system.site, system.catalog, system.db_path, Live(system.site.id, system.bus, system.clock),
                                   auth=Auth(no_login=True)))
    index = client.get("/api/help").json()
    assert index["statuses"][0]["status"] == "offline" and index["statuses"][0]["label"] == "Node offline"
    assert len(index["symptoms"]) == 5
    guide = client.get("/api/help/water_mismatch").json()
    assert guide["label"] == "Reservoir losing water" and "siphoning" in " ".join(guide["causes"])
    assert client.get("/api/help/ok").status_code == 404

    # a detection shows up in the log with a line a person can read
    system.sim.actuator_ignores("pothos-pump")
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.run(hours=2)
    system.hub.store.commit()
    row = client.get("/api/log", params={"group": "detection"}).json()["rows"][0]
    assert row["text"] == "actuator fault: pothos-pump did not acknowledge a command within 60 s" and row["level"] == "warn"


# --------------------------------------------------------------------------- fsf doctor

def doctor(system, **kwargs) -> Doctor:
    return Doctor(system.site, system.catalog, system.bus, wait=lambda s: system.run(seconds=max(s, system.tick)), **kwargs)


def test_doctor_passes_a_healthy_site(mock, tmp_path):
    system = mock("houseplants", db_path=str(tmp_path / "hub.db"), record_readings=True)
    system.run(hours=2)
    system.hub.store.commit()
    checks = doctor(system, db_path=system.db_path).run()
    by_name = {c.name: c for c in checks}
    failed = [str(c) for c in checks if not c.ok and not c.name.startswith("docker")]
    assert not failed, failed
    assert by_name["hub is publishing its state"].detail.startswith("version ")
    assert by_name["node shelf-node is online"].ok and by_name["zone pothos-window is healthy"].detail == "ok"
    assert "soil_moisture" in by_name["sensor pothos-soil reports plausible values"].detail
    assert "raw readings" in by_name["database is readable"].detail and by_name["disk has room"].ok
    assert "soil-adc" not in " ".join(by_name)          # a part in no zone is not expected to report


def test_doctor_names_each_failure_and_its_fix(mock):
    system = mock("mushrooms")
    system.run(hours=1)
    system.sim.sensor_dropout("inc-air")
    system.sim.node_offline("fruiting-node")
    system.run(minutes=30)
    failures = {c.name: c.detail for c in doctor(system).run() if not c.ok}
    assert "Fix: check its power and WiFi" in failures["node fruiting-node is online"]
    assert "min old. Fix: reseat the connector, then fsf bench inc-air" in failures["sensor inc-air reports plausible values"]
    assert "needs attention: sensor_stale" in failures["zone incubation-chamber is healthy"]
    assert "needs attention: offline" in failures["zone fruiting-chamber is healthy"]

    system.stop_hub()
    system.bus._retained.pop("fsf/mushrooms/hub/state")
    silent = {c.name: c for c in doctor(system).run()}
    assert not silent["hub is publishing its state"].ok and "that the hub is running" in silent["hub is publishing its state"].detail
    system.start_hub()


def test_doctor_bundle_holds_state_and_no_secrets(mock, tmp_path):
    system = mock("houseplants", db_path=str(tmp_path / "hub.db"))
    system.site.raw["mqtt"] = {"host": "broker.local", "password": "hunter2"}
    system.run(hours=1)
    system.hub.store.commit()
    checker = doctor(system, db_path=system.db_path)
    target = checker.bundle(checker.run(), tmp_path / "diagnostics.zip")
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == ["checks.json", "events.json", "live.json", "site.json"]
        everything = b"".join(archive.read(name) for name in archive.namelist())
        assert b"hunter2" not in everything
        assert json.loads(archive.read("site.json"))["mqtt"] == {"host": "broker.local", "password": "<redacted>"}
        assert json.loads(archive.read("live.json"))["nodes"] == {"shelf-node": "online"}
        assert any(e["kind"] == "planting_started" for e in json.loads(archive.read("events.json")))
    assert redact({"a": [{"api_key": "x", "ok": 1}]}) == {"a": [{"api_key": "<redacted>", "ok": 1}]}
