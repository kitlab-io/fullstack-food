"""Studio plan S2: the dashboard over a finished scenario run."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from fsf_sim import run_scenario  # noqa: E402
from fsf_web.replay import app_for_run  # noqa: E402

SCENARIO = "sites/examples/houseplants/scenarios/dry-pot-is-watered.yaml"


def test_a_live_site_has_no_scenario(served):
    _, client = served("houseplants")
    assert client.get("/api/scenario").json() == {"present": False}


def test_a_finished_run_is_shown_by_the_usual_pages(catalog, tmp_path):
    result = run_scenario(SCENARIO, catalog, out_dir=tmp_path, keep_system=True)
    try:
        client = TestClient(app_for_run(result))
        shown = client.get("/api/scenario").json()
        assert shown["present"] and shown["passed"] and shown["id"] == "dry-pot-is-watered"
        assert shown["timeline"][0]["text"] == "set_zone zone=pothos-window soil_moisture=20"
        assert len(shown["expectations"]) == 10 and all(e["ok"] for e in shown["expectations"])

        # the state at the end of the run, from the retained messages of its bus
        zones = {z["id"]: z for z in client.get("/api/zones").json()["zones"]}
        assert zones["pothos-window"]["status"] == "ok"
        assert client.get("/api/sim").json()["now"] == "2026-03-01T10:30:00+00:00"

        # the history, from the run's database: readings for the charts and the dose in the log
        series = client.get("/api/zones/pothos-window/series", params={"quantity": "soil_moisture"}).json()
        values = [v for v in series["mean"] if v is not None]
        assert min(values) < 21 and values[-1] > 30
        log = client.get("/api/log").json()
        assert any(row["kind"] == "dose" for row in log["rows"])

        # it is a record, not a site: reading is open and nothing can be done
        session = client.get("/api/session").json()
        assert (session["can_read"], session["can_act"]) == (True, False)
        assert client.post("/api/commands", json={"name": "water_now", "zone": "pothos-window"}).status_code == 401
        assert client.post("/api/sim", json={"name": "pause"}).status_code == 401
    finally:
        result.system.stop_hub()


def test_a_run_must_have_kept_its_system_to_be_shown(catalog):
    with pytest.raises(ValueError, match="keep its system"):
        app_for_run(run_scenario(SCENARIO, catalog))
