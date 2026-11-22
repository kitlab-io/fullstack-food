"""ESPHome configs generated from a site file."""

import copy
import shutil
import subprocess

import pytest
import yaml

from fsf_core import find_repo_root, load_site
from fsf_core.__main__ import main
from fsf_core.firmware import SECRETS, FirmwareError, build, build_node


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!secret", lambda loader, node: f"<secret {node.value}>")
_Loader.add_constructor("!lambda", lambda loader, node: node.value)


def _build(tmp_path, catalog, name: str) -> dict[str, dict]:
    site = load_site(find_repo_root() / "sites/examples" / name, catalog)
    written, _ = build(site, catalog, tmp_path, f"sites/examples/{name}/site.yaml", include_sim=True)
    return {p.stem: yaml.load(p.read_text(encoding="utf-8"), Loader=_Loader) for p in written}


def _text(node) -> str:
    return yaml.safe_dump(node)


def test_houseplants_node_speaks_the_contract(tmp_path, catalog):
    config = _build(tmp_path, catalog, "houseplants")["shelf-node"]
    assert config["esp32"] == {"board": "esp32-c3-devkitm-1", "framework": {"type": "esp-idf"}}
    assert config["i2c"] == {"sda": "GPIO5", "scl": "GPIO6"}

    mqtt = config["mqtt"]
    status = "fsf/houseplants/shelf-node/status"
    assert mqtt["birth_message"] == {"topic": status, "payload": "online", "retain": True}
    assert mqtt["will_message"] == {"topic": status, "payload": "offline", "retain": True}
    assert mqtt["discovery"] is False and mqtt["log_topic"] is None
    handled = [h["topic"] for h in mqtt["on_json_message"]]
    assert handled == [f"fsf/houseplants/shelf-node/{d}/cmd" for d in ("pothos-pump", "snake-pump", "status-strip")]

    # soil probes read through the I2C ADC and are scaled with the site's calibration
    raw = {s["id"]: s for s in config["sensor"] if s["platform"] == "ads1115"}
    assert raw["pothos_soil_raw"]["multiplexer"] == "A0_GND" and raw["snake_soil_raw"]["multiplexer"] == "A1_GND"
    assert raw["pothos_soil_raw"]["ads1115_id"] == "soil_adc_adc" and config["ads1115"][0]["id"] == "soil_adc_adc"
    moisture = next(s for s in config["sensor"] if s.get("id") == "pothos_soil_soil_moisture")
    assert moisture["filters"][0] == {"calibrate_linear": ["2.6 -> 0.0", "1.2 -> 100.0"]}

    states = _text(config["interval"])
    for device, quantity in (("room-air", "air_temperature"), ("pothos-soil", "soil_moisture"), ("reservoir-level", "water_level")):
        assert f"fsf/houseplants/shelf-node/{device}/state" in states and f'root["{quantity}"]' in states
    assert "soil-adc/state" not in states               # the ADC itself reports nothing


def test_every_actuator_gets_a_lease_that_the_node_ends_itself(tmp_path, catalog):
    for name in ("houseplants", "microgreens", "mushrooms"):
        site = load_site(find_repo_root() / "sites/examples" / name, catalog)
        for node, config in _build(tmp_path / name, catalog, name).items():
            in_firmware = [d for d in site.devices.values() if d.node == node and d.cls == "actuator"
                           and d.model["interface"]["bus"] != "mains_relay"]
            scripts = {s["id"]: s for s in config.get("script", [])}
            assert len(scripts) == len(in_firmware)
            for script in scripts.values():
                steps = [next(iter(step)) for step in script["then"]]
                delay = steps.index("delay")
                assert script["mode"] == "restart" and script["then"][delay] == {"delay": "return duration_ms;"}
                assert any(s in ("switch.turn_on", "output.set_level") for s in steps[:delay])
                assert any(s in ("switch.turn_off", "output.turn_off") for s in steps[delay:])
            for switch in config.get("switch", []):
                assert switch["restore_mode"] == "ALWAYS_OFF"       # everything off after a reboot
            for handler in config["mqtt"].get("on_json_message", []):
                assert "fsf_is_on(x)" in _text(handler) or "render" in _text(handler)


def test_mains_loads_are_left_out_with_a_warning(tmp_path, catalog):
    site = load_site(find_repo_root() / "sites/examples/mushrooms", catalog)
    _, warnings = build(site, catalog, tmp_path, "site.yaml", include_sim=True)
    assert len(warnings) == 2 and all("mains load, not in the firmware" in w for w in warnings)
    assert warnings[0].startswith("device inc-heater:") and warnings[1].startswith("device fr-humidifier:")
    configs = _build(tmp_path, catalog, "mushrooms")
    assert "script" not in configs["incubation-node"]
    fan = next(s for s in configs["fruiting-node"]["script"] if s["id"] == "fr_fan_lease")
    assert {"output.set_level": {"id": "fr_fan_pwm", "level": "return level;"}} in fan["then"]
    light = next(s for s in configs["fruiting-node"]["script"] if s["id"] == "fr_light_lease")
    assert [step["output.turn_off"] for step in light["then"] if "output.turn_off" in step] == ["fr_light_cold", "fr_light_warm"]


def test_no_secret_is_written(tmp_path, catalog):
    _build(tmp_path, catalog, "microgreens")
    text = (tmp_path / "tray-node.yaml").read_text(encoding="utf-8")
    for key in SECRETS:
        assert f"!secret '{key}'" in text or f"!secret {key}" in text
    example = yaml.safe_load((tmp_path / "secrets.example.yaml").read_text(encoding="utf-8"))
    assert example == dict.fromkeys(SECRETS, "")
    assert not (tmp_path / "secrets.yaml").exists()
    assert (tmp_path / "fsf_node.h").read_text(encoding="utf-8").count("fsf_draw") == 1


def test_missing_pins_and_calibration_are_reported_together(catalog):
    site = load_site(find_repo_root() / "sites/examples/houseplants", catalog)
    site = copy.deepcopy(site)
    del site.devices["pothos-pump"].raw["pins"]
    del site.devices["reservoir-level"].raw["calibration"]
    with pytest.raises(FirmwareError) as err:
        build_node(site, catalog, site.raw["nodes"][0])
    problems = "\n".join(err.value.problems)
    assert "device pothos-pump: no pin for gate; run `fsf validate --pins`" in problems
    assert "device reservoir-level: template needs ${cal.empty_cm}" in problems
    assert "device reservoir-level: template needs ${cal.full_cm}" in problems


def test_command_line_builds_only_real_nodes_unless_asked(tmp_path, capsys):
    example = str(find_repo_root() / "sites/examples/houseplants")
    assert main(["firmware", "build", example, "--out", str(tmp_path)]) == 1
    assert "no node with runtime esphome" in capsys.readouterr().out
    assert main(["firmware", "build", example, "--out", str(tmp_path), "--include-sim"]) == 0
    assert (tmp_path / "shelf-node.yaml").exists()
    assert main(["firmware", "flash", example, "shelf-node", "--out", str(tmp_path)]) == 1
    assert "secrets.yaml is missing" in capsys.readouterr().out.replace("\\", "/")


@pytest.mark.skipif(shutil.which("esphome") is None, reason="the esphome command is not installed")
def test_generated_configs_pass_esphome_validation(tmp_path, catalog):
    for name in ("houseplants", "microgreens", "mushrooms"):
        out = tmp_path / name
        configs = _build(out, catalog, name)
        (out / "secrets.yaml").write_text("".join(f'{k}: "example-{k}"\n' for k in SECRETS), encoding="utf-8")
        for node in configs:
            result = subprocess.run(["esphome", "config", str(out / f"{node}.yaml")], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
