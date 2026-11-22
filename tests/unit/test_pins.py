"""Pin assignments in a site file are checked against the board's pin map."""

import copy

import pytest
import yaml

from fsf_core import ConfigError, find_repo_root, load_site
from fsf_core.__main__ import main

EXAMPLE = "sites/examples/houseplants/site.yaml"


def _site(tmp_path, catalog, pins: dict[str, dict], example: str = EXAMPLE):
    """The example site with pins set on some devices: {device id: {signal: pin}}."""
    raw = copy.deepcopy(yaml.safe_load((find_repo_root() / example).read_text(encoding="utf-8")))
    for node in raw["nodes"]:
        for device in node["devices"]:
            if device["id"] in pins:
                device["pins"] = pins[device["id"]]
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_site(path, catalog)


def _problems(tmp_path, catalog, pins) -> str:
    with pytest.raises(ConfigError) as err:
        _site(tmp_path, catalog, pins)
    return "\n".join(err.value.problems)


def test_an_impossible_assignment_is_rejected_with_pins_that_would_work(tmp_path, catalog):
    problems = _problems(tmp_path, catalog, {"pothos-soil": {"adc": "GPIO6"}})
    assert "device pothos-soil: adc (adc): GPIO6 has no ADC; pins that can: GPIO0, GPIO1, GPIO3, GPIO4" in problems


def test_adc2_is_rejected_because_wifi_blocks_it(tmp_path, catalog):
    problems = _problems(tmp_path, catalog, {"pothos-soil": {"adc": "GPIO5"}})
    assert "GPIO5 is on ADC2, which cannot be read while WiFi is on; pins that can: GPIO0" in problems


def test_every_pin_problem_is_reported_at_once(tmp_path, catalog):
    problems = _problems(tmp_path, catalog, {
        "pothos-soil": {"adc": "GPIO0"},
        "snake-soil": {"adc": "GPIO0"},                         # same pin twice
        "pothos-pump": {"gate": "GPIO42"},                      # not on the board
        "room-air": {"sda": "GPIO6", "scl": "GPIO7", "int": "GPIO10"},   # the model has no such signal
    })
    assert "device snake-soil: adc (adc): GPIO0 is already used by pothos-soil (adc)" in problems
    assert "device pothos-pump: gate (digital_out): board esp32-c3-devkitm has no pin GPIO42" in problems
    assert "device room-air: model bosch.bme280 has no signal 'int' (signals: sda, scl)" in problems


def test_i2c_devices_share_the_bus_pins(tmp_path, catalog):
    site = _site(tmp_path, catalog, {"tray-air": {"sda": "GPIO6", "scl": "GPIO7"},
                                     "tray-lux": {"sda": "GPIO6", "scl": "GPIO7"}},
                 example="sites/examples/microgreens/site.yaml")
    assert not site.warnings
    assert "tray-air" not in site.pin_proposals and "tray-lux" not in site.pin_proposals


def test_caution_pins_load_with_a_warning_and_are_never_proposed(tmp_path, catalog):
    site = _site(tmp_path, catalog, {"status-strip": {"data": "GPIO20"}})
    assert site.warnings == ["device status-strip: data on GPIO20: UART0 RX: shared with the USB serial bridge "
                             "used for flashing and logs"]
    board = catalog.get("Board", "esp32-c3-devkitm")
    proposed = {pin for pins in site.pin_proposals.values() for pin in pins.values()}
    assert proposed and not any("caution" in board["pins"][pin] for pin in proposed)
    assert not site.pin_unassigned                      # with the strip placed by hand, everything fits


def test_blank_pins_get_a_proposal_that_passes_validation(tmp_path, catalog):
    site = load_site(find_repo_root() / "sites/examples/mushrooms", catalog)
    assert site.pin_proposals["fr-climate"] == {"sda": "GPIO5", "scl": "GPIO6"}
    assert site.pin_proposals["inc-air"] == {"sda": "GPIO5", "scl": "GPIO6"}      # another node, its own pins
    assert "inc-heater" not in site.pin_proposals       # mains load on a smart plug: no board pins
    assert not site.pin_unassigned

    again = _site(tmp_path, catalog, site.pin_proposals, example="sites/examples/mushrooms/site.yaml")
    assert not again.pin_proposals and not again.warnings and not again.pin_unassigned


def test_a_build_that_needs_more_pins_than_the_board_has_says_so(catalog):
    site = load_site(find_repo_root() / EXAMPLE, catalog)
    assert site.pin_proposals["pothos-soil"] == {"adc": "GPIO0"}      # analog inputs get the ADC pins first
    assert site.pin_unassigned[0] == "device status-strip: no free pin on esp32-c3-devkitm for data (led_data)"
    assert "needs more pins than esp32-c3-devkitm has free" in site.pin_unassigned[1]


def test_validate_command_prints_proposals_on_request(capsys):
    assert main(["validate"]) == 0
    assert "propose" not in capsys.readouterr().out
    assert main(["validate", "--pins"]) == 0
    out = capsys.readouterr().out
    assert "propose: fr-climate: pins: { sda: GPIO5, scl: GPIO6 }" in out
    assert "no pin: device status-strip" in out


def test_models_of_the_example_sites_carry_assembly_and_test_data(catalog):
    """Installation plan I1: every part an example site uses says how to wire, power and test it."""
    used = set()
    for name in ("houseplants", "microgreens", "mushrooms"):
        site = load_site(find_repo_root() / "sites/examples" / name, catalog)
        used |= {dev.model["id"] for dev in site.devices.values()}
    assert len(used) == 14
    for model_id in sorted(used):
        model = catalog.get("Model", model_id)
        missing = [key for key in ("power", "bench_test", "troubleshooting") if key not in model]
        assert not missing, f"{model_id} lacks {missing}"
        assert model["datasheet_checked"] is False       # nothing has been confirmed on hardware yet
        if model["interface"]["bus"] == "mains_relay":
            assert "pins" not in model and "mains" in model["safety"]["hazards"]
        else:
            assert model["pins"], model_id
