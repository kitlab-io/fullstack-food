"""Installation plan I6: starting a real site, its credentials, and what has been verified where."""

import base64
import hashlib
from pathlib import Path

import yaml

from fsf_core import find_repo_root, load_site
from fsf_core.__main__ import main
from fsf_core.builddocs import compatibility, compatibility_html, compatibility_markdown
from fsf_core.firmware import build
from fsf_core.init import acl, init, mosquitto_hash

EXAMPLE = find_repo_root() / "sites/examples/mushrooms"


def _env(path: Path) -> dict:
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))


def test_init_creates_a_site_with_its_own_id_and_credentials(tmp_path, catalog):
    written = init("my-grow", EXAMPLE, find_repo_root(), catalog, tmp_path)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in written) == [
        "broker/acl", "broker/passwd", "hub.env", "operator.env", "secrets.yaml", "site.yaml", "web.env"]
    site = load_site(tmp_path, catalog)
    assert site.id == "my-grow" and len(site.devices) == 8

    secrets = yaml.safe_load((tmp_path / "secrets.yaml").read_text(encoding="utf-8"))
    assert secrets["wifi_ssid"] == "" and secrets["mqtt_host"] == ""         # for the person to fill in
    assert secrets["fruiting_node_mqtt_username"] == "node-fruiting-node"
    passwords = [v for k, v in secrets.items() if k.endswith("password") and v] + [
        _env(tmp_path / f"{s}.env")["FSF_MQTT_PASSWORD"] for s in ("hub", "web", "operator")]
    assert len(passwords) == len(set(passwords)) == 7 and all(len(p) >= 20 for p in passwords)     # all different, all long
    assert _env(tmp_path / "web.env")["FSF_WEB_PASSWORD_HASH"] == ""

    users = dict(line.split(":", 1) for line in (tmp_path / "broker/passwd").read_text(encoding="utf-8").splitlines())
    assert set(users) == {"hub", "web", "operator", "node-incubation-node", "node-fruiting-node", "node-plug-strip"}
    stored = "".join(users.values())
    assert not any(p in stored for p in passwords)       # hashes only


def test_password_file_entries_use_mosquittos_own_format():
    entry = mosquitto_hash("s3cret", salt=b"0123456789ab")
    marker, version, iterations, salt, digest = entry.split("$")
    assert (marker, version, iterations) == ("", "7", "101") and base64.b64decode(salt) == b"0123456789ab"
    assert base64.b64decode(digest) == hashlib.pbkdf2_hmac("sha512", b"s3cret", b"0123456789ab", 101, dklen=64)
    assert mosquitto_hash("s3cret") != mosquitto_hash("s3cret")             # salted


def test_acl_confines_each_login_to_what_it_needs():
    text = acl("my-grow", ["shelf-node", "plug-strip"])
    blocks = {b.splitlines()[0].split()[1]: b.splitlines()[1:] for b in text.split("\n\n") if b.lstrip("# \n").startswith("user")
              or "\nuser " in b for b in [b[b.index("user "):]]}
    assert blocks["hub"] == ["topic readwrite fsf/my-grow/#"]
    assert blocks["web"] == ["topic read fsf/my-grow/#", "topic write fsf/my-grow/hub/cmd"]     # it can only ask the hub
    assert blocks["node-shelf-node"] == ["topic write fsf/my-grow/shelf-node/#", "topic read fsf/my-grow/shelf-node/+/cmd"]
    assert "shelf-node" not in " ".join(blocks["node-plug-strip"])


def test_running_init_again_keeps_passwords_and_adds_new_nodes(tmp_path, catalog):
    init("my-grow", EXAMPLE, find_repo_root(), catalog, tmp_path)
    secrets_file = tmp_path / "secrets.yaml"
    filled = yaml.safe_load(secrets_file.read_text(encoding="utf-8"))
    filled.update(wifi_ssid="home", wifi_password="hunter22", mqtt_host="growhub.local")
    secrets_file.write_text(yaml.safe_dump(filled), encoding="utf-8")
    hub_before = _env(tmp_path / "hub.env")

    site_file = tmp_path / "site.yaml"
    raw = yaml.safe_load(site_file.read_text(encoding="utf-8"))
    raw["nodes"].append({"id": "shed-node", "board": "esp32-c3-devkitm", "runtime": "sim", "devices": []})
    site_file.write_text(yaml.safe_dump(raw), encoding="utf-8")

    init("my-grow", EXAMPLE, find_repo_root(), catalog, tmp_path)
    after = yaml.safe_load(secrets_file.read_text(encoding="utf-8"))
    assert {k: after[k] for k in filled} == filled                          # nothing a person entered is lost
    assert after["shed_node_mqtt_username"] == "node-shed-node" and after["shed_node_mqtt_password"]
    assert _env(tmp_path / "hub.env") == hub_before
    assert "user node-shed-node" in (tmp_path / "broker/acl").read_text(encoding="utf-8")
    assert yaml.safe_load(site_file.read_text(encoding="utf-8"))["nodes"][-1]["id"] == "shed-node"      # the site file is left alone


def test_firmware_build_uses_the_sites_own_secrets(tmp_path, catalog):
    init("my-grow", EXAMPLE, find_repo_root(), catalog, tmp_path / "site")
    site = load_site(tmp_path / "site", catalog)
    build(site, catalog, tmp_path / "out", "site.yaml", include_sim=True, secrets_file=tmp_path / "site" / "secrets.yaml")
    copied = yaml.safe_load((tmp_path / "out" / "secrets.yaml").read_text(encoding="utf-8"))
    config = (tmp_path / "out" / "fruiting-node.yaml").read_text(encoding="utf-8")
    assert "fruiting_node_mqtt_password" in copied and "!secret 'fruiting_node_mqtt_password'" in config
    assert copied["fruiting_node_mqtt_password"] not in config             # the config names the secret, never holds it


def test_init_command_and_bad_names(tmp_path, capsys):
    assert main(["init", "My Site!", "--from", str(EXAMPLE), "--dir", str(tmp_path / "x")]) == 1
    assert "lowercase letters" in capsys.readouterr().out
    assert main(["init", "greenhouse", "--from", str(EXAMPLE), "--dir", str(tmp_path / "g")]) == 0
    out = capsys.readouterr().out
    assert "secrets.yaml" in out and "deploy/compose/sbc.yaml" in out
    assert main(["validate", str(tmp_path / "g")]) == 0


def test_compatibility_matrix_says_plainly_that_nothing_is_verified_on_hardware(catalog, tmp_path, capsys):
    data = compatibility(catalog)
    assert data["verified_on_hardware"] == []
    pump = next(p for p in data["parts"] if p["id"] == "generic.12v-peristaltic-pump")
    assert pump["drivers"] == {"esphome": {"status": "untested", "tested_on": []}, "sim": {"status": "verified", "tested_on": []}}
    strip = next(b for b in data["boards"] if b["id"] == "tplink.kasa-hs300")
    assert strip["class"] == "smart_plug" and strip["runtimes"] == ["kasa", "sim"]

    text = compatibility_markdown(catalog)
    assert "**No part is verified on real hardware yet.**" in text
    assert "| 12 V peristaltic pump | untested | – | – | – | verified | no |" in text
    assert "| ESP32-C3-DevKitM-1 | mcu | esphome, circuitpython | – | yes, unconfirmed |" in text
    html = compatibility_html(catalog)
    assert "<h1>Compatibility</h1>" in html and html.count("<table>") == 2 and "TP-Link Kasa HS300" in html

    assert main(["docs", "compatibility", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "compatibility.md").exists() and (tmp_path / "compatibility.html").exists()


def test_deploy_files_for_a_real_hub_are_consistent():
    root = find_repo_root()
    conf = (root / "deploy/compose/mosquitto-auth.conf").read_text(encoding="utf-8")
    assert "allow_anonymous false" in conf and "password_file /mosquitto/config/passwd" in conf and "acl_file" in conf
    sbc = yaml.safe_load((root / "deploy/compose/sbc.yaml").read_text(encoding="utf-8").replace("!override", "").replace("!reset null", ""))
    assert any(v.endswith("/broker/passwd:/mosquitto/config/passwd:ro") for v in sbc["services"]["broker"]["volumes"])
    assert sbc["services"]["hub"]["env_file"].endswith("/hub.env") and sbc["services"]["web"]["env_file"].endswith("/web.env")
    script = (root / "deploy/os/provision.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in script and "NOT YET RUN" in script
