"""Pin assignments in a site file are checked against the board's pin map."""

import copy

import pytest
import yaml

from fsf_core import ConfigError, find_repo_root, load_site
from fsf_core.__main__ import main

HOUSEPLANTS = "sites/examples/houseplants/site.yaml"


def _site(tmp_path, catalog, pins: dict[str, dict], example: str = HOUSEPLANTS, without: tuple[str, ...] = ()):
    """An example site with every pin cleared, then `pins` set: {device id: {signal: pin}}.

    `without` drops devices (and their zone memberships), e.g. the I2C ADC.
    """
    raw = copy.deepcopy(yaml.safe_load((find_repo_root() / example).read_text(encoding="utf-8")))
    for node in raw["nodes"]:
        node["devices"] = [d for d in node["devices"] if d["id"] not in without]
        for device in node["devices"]:
            device.pop("pins", None)
            if device["id"] in pins:
                device["pins"] = pins[device["id"]]
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_site(path, catalog)


def _problems(tmp_path, catalog, pins, **kwargs) -> str:
    with pytest.raises(ConfigError) as err:
        _site(tmp_path, catalog, pins, **kwargs)
    return "\n".join(err.value.problems)


def test_example_sites_have_every_pin_assigned(catalog):
    for name in ("houseplants", "microgreens", "mushrooms"):
        site = load_site(find_repo_root() / "sites/examples" / name, catalog)
        assert not site.pin_proposals and not site.pin_unassigned and not site.warnings, name


def test_an_impossible_assignment_is_rejected_with_pins_that_would_work(tmp_path, catalog):
    problems = _problems(tmp_path, catalog, {"pothos-soil": {"adc": "GPIO6"}}, without=("soil-adc",))
    assert "device pothos-soil: adc (adc): GPIO6 has no ADC; pins that can: GPIO0, GPIO1, GPIO3, GPIO4" in problems


def test_adc2_is_rejected_because_wifi_blocks_it(tmp_path, catalog):
    problems = _problems(tmp_path, catalog, {"pothos-soil": {"adc": "GPIO5"}}, without=("soil-adc",))
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
    shared = {"sda": "GPIO6", "scl": "GPIO7"}
    site = _site(tmp_path, catalog, {"tray-air": shared, "tray-lux": shared, "soil-adc": shared},
                 example="sites/examples/microgreens/site.yaml")
    assert not site.warnings
    assert not {"tray-air", "tray-lux", "soil-adc"} & set(site.pin_proposals)


def test_a_probe_can_sit_on_a_channel_of_the_i2c_adc(tmp_path, catalog):
    site = _site(tmp_path, catalog, {"pothos-soil": {"adc": "soil-adc/A2"}})
    assert site.pin_proposals["snake-soil"] == {"adc": "soil-adc/A0"}     # blanks go to free channels first
    assert site.pin_proposals["soil-adc"] == site.pin_proposals["room-air"]
    assert not site.pin_unassigned                      # with the probes off the board, everything fits

    problems = _problems(tmp_path, catalog, {"pothos-soil": {"adc": "soil-adc/A0"}, "snake-soil": {"adc": "soil-adc/A0"},
                                             "pothos-pump": {"gate": "soil-adc/A1"},
                                             "reservoir-level": {"trigger": "GPIO0", "echo": "soil-adc/A7"}})
    assert "device snake-soil: adc (adc): soil-adc/A0 is already used by pothos-soil (adc)" in problems
    assert "device pothos-pump: gate (digital_out): soil-adc/A1 provides adc, not digital_out" in problems
    assert "device reservoir-level: echo (digital_in): node shelf-node has no channel soil-adc/A7" in problems


def test_caution_pins_load_with_a_warning_and_are_never_proposed(tmp_path, catalog):
    site = _site(tmp_path, catalog, {"status-strip": {"data": "GPIO20"}})
    assert site.warnings == ["device status-strip: data on GPIO20: UART0 RX: shared with the USB serial bridge "
                             "used for flashing and logs"]
    board = catalog.get("Board", "esp32-c3-devkitm")
    proposed = {pin for pins in site.pin_proposals.values() for pin in pins.values() if "/" not in pin}
    assert proposed and not any("caution" in board["pins"][pin] for pin in proposed)


def test_blank_pins_get_a_proposal_that_passes_validation(tmp_path, catalog):
    example = "sites/examples/mushrooms/site.yaml"
    site = _site(tmp_path, catalog, {}, example=example)
    assert site.pin_proposals["fr-climate"] == {"sda": "GPIO5", "scl": "GPIO6"}
    assert site.pin_proposals["inc-air"] == {"sda": "GPIO5", "scl": "GPIO6"}      # another node, its own pins
    assert "inc-heater" not in site.pin_proposals       # mains load on a smart plug: no board pins
    assert not site.pin_unassigned

    again = _site(tmp_path, catalog, site.pin_proposals, example=example)
    assert not again.pin_proposals and not again.warnings and not again.pin_unassigned


def test_a_build_that_needs_more_pins_than_the_board_has_says_so(tmp_path, catalog):
    """Without the I2C ADC the house plant build is one pin short on this board."""
    site = _site(tmp_path, catalog, {}, without=("soil-adc",))
    assert site.pin_proposals["pothos-soil"] == {"adc": "GPIO0"}      # analog inputs get the ADC pins first
    assert site.pin_unassigned[0] == "device status-strip: no free pin on esp32-c3-devkitm for data (led_data)"
    assert "needs more pins than esp32-c3-devkitm has free" in site.pin_unassigned[1]


def test_validate_command_prints_proposals_on_request(tmp_path, catalog, capsys):
    _site(tmp_path, catalog, {}, example="sites/examples/mushrooms/site.yaml")
    assert main(["validate", str(tmp_path / "site.yaml")]) == 0
    assert "propose" not in capsys.readouterr().out
    assert main(["validate", "--pins", str(tmp_path / "site.yaml")]) == 0
    assert "propose: fr-climate: pins: { sda: GPIO5, scl: GPIO6 }" in capsys.readouterr().out


def test_models_of_the_example_sites_carry_assembly_and_test_data(catalog):
    """Installation plan I1: every part an example site uses says how to wire, power and test it."""
    used = set()
    for name in ("houseplants", "microgreens", "mushrooms"):
        site = load_site(find_repo_root() / "sites/examples" / name, catalog)
        used |= {dev.model["id"] for dev in site.devices.values()}
    assert len(used) == 15
    for model_id in sorted(used):
        model = catalog.get("Model", model_id)
        missing = [key for key in ("power", "bench_test", "troubleshooting") if key not in model]
        assert not missing, f"{model_id} lacks {missing}"
        assert model["datasheet_checked"] is False       # nothing has been confirmed on hardware yet
        if model["interface"]["bus"] == "mains_relay":
            assert "pins" not in model and "mains" in model["safety"]["hazards"]
        else:
            assert model["pins"], model_id
