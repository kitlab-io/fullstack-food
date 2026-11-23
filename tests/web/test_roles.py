"""Studio plan S1: viewer, operator and admin logins."""

import shutil

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from fsf_core import find_repo_root  # noqa: E402
from fsf_studio import RevisionStore  # noqa: E402
from fsf_web import create_app  # noqa: E402
from fsf_web.auth import Auth, hash_password  # noqa: E402

PASSWORDS = {"viewer": "just looking 1", "operator": "hands on 22", "admin": "keys to it all 333"}
PAUSE = {"name": "pause_zone", "zone": "pothos-window"}


@pytest.fixture
def roles(served, tmp_path):
    system, _ = served("houseplants")
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    shutil.copyfile(find_repo_root() / "sites/examples/houseplants/site.yaml", site_dir / "site.yaml")
    RevisionStore(site_dir, system.catalog).save("ada", "as built")
    auth = Auth(hash_password(PASSWORDS["operator"]), viewer_hash=hash_password(PASSWORDS["viewer"]),
                admin_hash=hash_password(PASSWORDS["admin"]))

    def client_as(role: str | None):
        client = TestClient(create_app(system.site, system.catalog, system.db_path, system.live, auth=auth, site_dir=site_dir))
        headers = {}
        if role:
            session = client.post("/api/login", json={"password": PASSWORDS[role], "name": role}).json()
            assert session["role"] == role
            headers = {"X-CSRF-Token": session["csrf"]}
        return client, headers

    return system, client_as


def test_the_password_decides_the_role(roles):
    _, client_as = roles
    client, _ = client_as("viewer")
    assert client.get("/api/session").json() | {"csrf": None} == {
        "login_required": True, "authenticated": True, "role": "viewer", "can_read": True, "can_act": False,
        "can_admin": False, "name": "viewer", "csrf": None, "password_configured": True}
    assert client_as("operator")[0].get("/api/session").json()["can_act"] is True
    admin = client_as("admin")[0].get("/api/session").json()
    assert (admin["can_read"], admin["can_act"], admin["can_admin"]) == (True, True, True)


def test_a_viewer_can_read_but_not_act(roles):
    system, client_as = roles
    client, headers = client_as("viewer")
    assert client.get("/api/zones").status_code == 200
    refused = client.post("/api/commands", json=PAUSE, headers=headers)
    assert refused.status_code == 403 and refused.json()["detail"] == "this needs the operator login; you are logged in as viewer"
    assert client.post("/api/sim", json={"name": "pause"}, headers=headers).status_code == 403
    assert "pothos-window" not in system.hub.paused
    assert client.post("/api/logout", headers=headers).status_code == 200      # but can always log out


def test_an_operator_can_act_but_not_reach_the_studio(roles):
    system, client_as = roles
    client, headers = client_as("operator")
    assert client.post("/api/commands", json=PAUSE, headers=headers).json()["ok"] is True
    assert system.events("command")[0]["by"] == "dashboard:operator"
    refused = client.get("/api/studio/revisions")
    assert refused.status_code == 403 and "needs the admin login" in refused.json()["detail"]


def test_an_admin_sees_the_revisions(roles):
    _, client_as = roles
    client, _ = client_as("admin")
    body = client.get("/api/studio/revisions").json()
    assert body["applied"] is None and body["draft_changes"] == []
    assert [(r["number"], r["by"], r["message"]) for r in body["revisions"]] == [(1, "ada", "as built")]
    assert client_as(None)[0].get("/api/studio/revisions").status_code == 401


def test_a_role_without_a_hash_cannot_be_logged_in_to(served):
    system, _ = served("houseplants")
    auth = Auth(hash_password(PASSWORDS["operator"]))                   # only the operator is configured
    client = TestClient(create_app(system.site, system.catalog, system.db_path, system.live, auth=auth))
    assert client.post("/api/login", json={"password": PASSWORDS["admin"]}).status_code == 401
    assert client.post("/api/login", json={"password": PASSWORDS["operator"]}).json()["role"] == "operator"
    assert client.get("/api/studio/revisions").status_code == 403       # an operator, and no admin exists


def test_open_modes_map_to_roles(served):
    system, client = served("houseplants")                              # the mock stack: no login at all
    assert client.get("/api/session").json()["role"] == "admin"
    reading = TestClient(create_app(system.site, system.catalog, system.db_path, system.live,
                                    auth=Auth(hash_password(PASSWORDS["operator"]), read_without_login=True)))
    session = reading.get("/api/session").json()
    assert (session["role"], session["can_read"], session["can_act"], session["can_admin"]) == ("viewer", True, False, False)
