"""Dashboard plan D4: the login, and actions that go through the hub."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from fsf_web import create_app  # noqa: E402
from fsf_web.auth import COOKIE, Auth, hash_password, verify_password  # noqa: E402

PASSWORD = "correct horse battery"


@pytest.fixture
def locked(served):
    """(system, client, auth, tick) with the login switched on; tick(seconds) moves the login's clock."""
    def make(name: str, **options):
        system, _ = served(name)
        now = [1000.0]
        auth = Auth(hash_password(PASSWORD), clock=lambda: now[0], **options)
        client = TestClient(create_app(system.site, system.catalog, system.db_path, system.live, auth=auth))
        return system, client, auth, lambda seconds: now.__setitem__(0, now[0] + seconds)
    return make


def sign_in(client, name="ada") -> dict:
    response = client.post("/api/login", json={"password": PASSWORD, "name": name})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_password_hashes_are_salted_and_verify():
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt:") and PASSWORD not in stored and stored != hash_password(PASSWORD)
    assert verify_password(PASSWORD, stored) and not verify_password("wrong", stored)
    assert not verify_password(PASSWORD, "not-a-hash") and not verify_password(PASSWORD, "md5:1:1:1:aa:bb")


def test_nothing_is_readable_or_doable_without_the_login(locked):
    system, client, _, _ = locked("mushrooms")
    for path in ("/api/zones", "/api/site", "/api/devices", "/api/log", "/api/stream", "/api/export/diagnostics"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/commands", json={"name": "pause_zone", "zone": "incubation-chamber"}).status_code == 401
    assert client.get("/api/session").json() == {
        "login_required": True, "authenticated": False, "can_read": False, "can_act": False, "name": None, "csrf": None,
        "password_configured": True}
    assert client.get("/api/health").status_code == 200
    assert "incubation-chamber" not in system.hub.paused


def test_login_sets_a_strict_http_only_cookie_and_logout_ends_the_session(locked):
    _, client, _, _ = locked("mushrooms")
    assert client.post("/api/login", json={"password": "guess"}).json() == {"detail": "wrong password"}
    response = client.post("/api/login", json={"password": PASSWORD, "name": "  Ada\n"})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and COOKIE in cookie
    session = response.json()
    assert session["authenticated"] and session["name"] == "Ada" and len(session["csrf"]) > 20
    assert client.get("/api/zones").status_code == 200

    assert client.post("/api/logout").status_code == 403                # even logging out needs the CSRF token
    assert client.post("/api/logout", headers={"X-CSRF-Token": session["csrf"]}).status_code == 200
    assert client.get("/api/zones").status_code == 401


def test_actions_need_the_csrf_token_and_are_logged_with_who_did_them(locked):
    system, client, _, _ = locked("mushrooms")
    headers = sign_in(client)
    command = {"name": "pause_zone", "zone": "incubation-chamber", "duration": "1h"}
    assert client.post("/api/commands", json=command).status_code == 403
    assert client.post("/api/commands", json=command, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert "incubation-chamber" not in system.hub.paused

    reply = client.post("/api/commands", json={**command, "by": "mallory", "id": "chosen"}, headers=headers).json()
    assert reply["ok"] and reply["name"] == "pause_zone" and reply["id"] != "chosen"
    assert "incubation-chamber" in system.hub.paused
    (logged,) = system.events("command")
    assert logged["by"] == "dashboard:ada"              # who is taken from the session, not from the request


def test_sessions_expire_and_wrong_passwords_lock_the_login(locked):
    _, client, _, tick = locked("mushrooms")
    sign_in(client)
    tick(12 * 3600 + 1)
    assert client.get("/api/zones").status_code == 401

    for _ in range(5):
        assert client.post("/api/login", json={"password": "guess"}).status_code == 401
    locked_out = client.post("/api/login", json={"password": PASSWORD})
    assert locked_out.status_code == 401 and "too many wrong passwords" in locked_out.json()["detail"]
    tick(61)
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200


def test_reading_can_be_opened_while_actions_stay_behind_the_login(locked):
    system, client, _, _ = locked("mushrooms", read_without_login=True)
    assert client.get("/api/zones").status_code == 200
    assert client.get("/api/session").json()["can_read"] is True and client.get("/api/session").json()["can_act"] is False
    assert client.post("/api/commands", json={"name": "pause_zone", "zone": "incubation-chamber"}).status_code == 401


def test_without_a_configured_password_nobody_gets_in(served):
    system, _ = served("mushrooms")
    client = TestClient(create_app(system.site, system.catalog, system.db_path, system.live))
    assert client.get("/api/zones").status_code == 401
    assert "no password is configured" in client.post("/api/login", json={"password": ""}).json()["detail"]
    assert client.get("/api/session").json()["password_configured"] is False


def test_commands_return_the_hubs_reply_including_its_refusals(served):
    system, client = served("houseplants")
    system.run(minutes=5)
    watered = client.post("/api/commands", json={"name": "water_now", "zone": "pothos-window"}).json()
    assert watered["ok"] and watered["result"]["volume_ml"] == 150 and system.is_on("pothos-pump")
    again = client.post("/api/commands", json={"name": "water_now", "zone": "pothos-window"}).json()
    assert again == {"id": again["id"], "name": "water_now", "t": again["t"], "ok": False,
                     "error": "blocked: a dose is already running"}
    assert system.events("command")[0]["by"] == "dashboard"

    assert client.post("/api/commands", json={"name": "commission", "scope": "device", "subject": "pothos-pump",
                                              "step": "bench", "ok": True}).status_code == 422
    assert client.post("/api/commands", json={"name": "set_override", "zone": "pothos-window"}).status_code == 422
    assert client.post("/api/commands", json={"name": "actuator_test", "device": "snake-pump", "duration_s": 99}).status_code == 422
    system.stop_hub()
    silent = client.post("/api/commands", json={"name": "pause_zone", "zone": "pothos-window"})
    assert silent.status_code == 504 and "did not answer" in silent.json()["detail"]
    system.start_hub()


def test_zone_view_says_what_can_be_done_next(served):
    system, client = served("mushrooms")
    zones = {z["id"]: z for z in client.get("/api/zones").json()["zones"]}
    assert zones["incubation-chamber"]["actions"] == {"water": None, "advance": {
        "planting": "oyster-1", "to_stage": "fruiting", "to_zone": "fruiting-chamber", "blocked": None}}
    assert zones["fruiting-chamber"]["actions"] == {"water": None, "advance": None}

    for expected in (("fruiting", "fruiting-chamber"), ("harvest", "fruiting-chamber")):
        advance = client.post("/api/commands", json={"name": "advance_stage", "planting": "oyster-1"}).json()
        assert advance["ok"] and advance["result"] == {"stage": expected[0]}
        system.run(minutes=1)
        zone = client.get(f"/api/zones/{expected[1]}").json()
        assert zone["planting"]["stage"] == expected[0]
    assert zone["actions"]["advance"] == {"planting": "oyster-1", "to_stage": None, "to_zone": None, "blocked": None}

    houseplants, plants = served("houseplants")
    pothos = plants.get("/api/zones/pothos-window").json()
    assert pothos["actions"]["water"] == {"loop": "watering", "volume_ml": 150}
