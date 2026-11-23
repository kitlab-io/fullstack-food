"""Installation plan I4: build documents generated from a site file and the catalog."""

import csv
import io
import re
import xml.etree.ElementTree as ET

import pytest

from fsf_core import find_repo_root, load_site
from fsf_core.__main__ import main
from fsf_core.builddocs import bom, bom_csv, build, build_guide_html, checklist_html, legend_html, power_budget, wiring_svg


@pytest.fixture(scope="module")
def sites(catalog):
    return {name: load_site(find_repo_root() / "sites/examples" / name, catalog)
            for name in ("houseplants", "microgreens", "mushrooms")}


def test_bom_lists_parts_their_support_parts_and_sized_supplies(sites, catalog):
    rows = {r["item"]: r for r in bom(sites["houseplants"], catalog)}
    assert rows["ESP32-C3-DevKitM-1"]["category"] == "board"
    pumps = rows["12 V peristaltic pump"]
    assert pumps["qty"] == 2 and pumps["used_by"] == "pothos-pump, snake-pump" and "not yet confirmed" in pumps["note"]
    assert rows["1N5819 diode"]["qty"] == 2 and rows["logic-level N-channel MOSFET"]["qty"] == 2    # one per pump
    # the I2C pull-ups are needed once per bus, not once per I2C device
    pullups = rows["4.7 kOhm resistor"]
    assert pullups["qty"] == 2 and pullups["used_by"] == "shelf-node" and "only if" in pullups["note"]
    assert rows["12 V power supply, at least 1.5 A"]["note"] == "peak 1.00 A plus 30 % margin"
    assert rows["5 V power supply, at least 2.5 A"]["category"] == "supply"

    table = list(csv.DictReader(io.StringIO(bom_csv(list(rows.values())))))
    assert len(table) == len(rows) and set(table[0]) == {"category", "item", "qty", "used_by", "note"}


def test_power_budget_adds_up_per_rail_and_warns(sites, catalog):
    (shelf,) = power_budget(sites["houseplants"], catalog)
    strip = next(ld for ld in shelf["rails"]["5v"]["loads"] if ld["device"] == "status-strip")
    assert strip == {"device": "status-strip", "peak_ma": 1600, "note": "20 LEDs"}     # 80 mA per LED
    assert shelf["rails"]["5v"]["peak_ma"] == 1615 and shelf["rails"]["5v"]["supply_a"] == 2.5
    assert shelf["rails"]["12v"]["peak_ma"] == 1000 and shelf["rails"]["3v3"]["peak_ma"] == 15
    assert shelf["warnings"] == ["5 V rail peaks at 1.6 A: feed it from its own supply, not through the board's 5 V pin or USB port"]

    fruiting = next(e for e in power_budget(sites["mushrooms"], catalog) if e["node"] == "fruiting-node")
    assert fruiting["rails"]["12v"]["unknown"] == ["fr-heater", "fr-light"]
    assert "current of fr-heater, fr-light is not in the catalog" in fruiting["warnings"][0]
    assert fruiting["rails"]["mains"]["unknown"] == ["fr-humidifier"]
    supply = next(r for r in bom(sites["mushrooms"], catalog) if r["item"].startswith("12 V power supply") and r["used_by"] == "fruiting-node")
    assert "not counted: fr-heater, fr-light" in supply["note"]


def test_wiring_diagram_is_valid_svg_showing_every_assigned_signal(sites, catalog):
    site = sites["houseplants"]
    svg = wiring_svg(site, catalog, "shelf-node")
    root = ET.fromstring(svg)                           # well-formed
    assert root.tag.endswith("svg")
    text = " ".join("".join(t.itertext()) for t in root.iter("{http://www.w3.org/2000/svg}text"))
    for device in site.devices.values():
        assert device.id in text
        for signal, pin in device.raw.get("pins", {}).items():
            where = pin.replace("/", " channel ")
            assert re.search(rf"{signal}[^a-z]* . {re.escape(where)}", text), (device.id, signal, pin)
    assert "adc → soil-adc channel A0" in text and "echo (5 V!) ← GPIO1" in text
    paths = root.findall("{http://www.w3.org/2000/svg}path")
    on_board = sum(1 for d in site.devices.values() for p in d.raw.get("pins", {}).values() if "/" not in p)
    assert len(paths) == on_board

    mushrooms = wiring_svg(sites["mushrooms"], catalog, "incubation-node")
    assert "Mains: through a certified smart plug. No board wiring." in mushrooms
    ET.fromstring(mushrooms)


def test_build_guide_orders_steps_and_ends_each_in_a_test(sites, catalog):
    html = build_guide_html(sites["houseplants"], catalog)
    assert html.startswith("<!doctype html>") and "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "Not yet confirmed on hardware" in html
    steps = re.findall(r'<div class="step"><strong>Step (\d+)\. ([^<]+)</strong>', html)
    assert [int(n) for n, _ in steps] == list(range(1, len(steps) + 1))
    names = [name.rstrip(".") for _, name in steps]
    assert names[0] == "Flash the bare board"
    assert names.index("soil-adc") < names.index("pothos-soil")            # the ADC before the probes that plug into it
    assert names.index("room-air") < names.index("pothos-pump")            # sensors before actuators
    assert names[-3:] == ["Node acceptance", "Zone pothos-window", "Zone snake-shelf"]
    assert html.count('<div class="test">') >= len(steps)                   # every step ends in a test
    assert "fsf bench pothos-pump" in html and "fsf calibrate reservoir-level" in html
    assert "Connect adc to soil-adc/A0" in html and "1N5819 diode: flyback protection across the motor" in html
    assert "Fuse each 12 V rail" in html and "certified smart plug" not in html.split("2. Parts")[0]   # no mains here

    mushrooms = build_guide_html(sites["mushrooms"], catalog)
    assert "Mains loads are switched only through a certified smart plug" in mushrooms
    assert "Plug it into its smart plug. It has no wiring to the board." in mushrooms
    assert "fsf calibrate fr-climate" not in mushrooms                      # CO2 calibration is done by hand


def test_checklist_has_a_box_for_every_stage(sites, catalog):
    html = checklist_html(sites["mushrooms"], catalog)
    site = sites["mushrooms"]
    assert html.count("fsf bench ") == len(site.devices)
    assert html.count("fsf node test ") == 2 and html.count("fsf zone test ") == 2
    assert html.count('<span class="box">') == len(site.devices) + 2 + 3 * 2 + 1      # bench, node tests, zone stages, strip


def test_legend_card_matches_the_theme_and_the_strip_layout(sites, catalog):
    html = legend_html(sites["houseplants"], catalog)
    assert "LEDs 0–9</td><td>pothos-window" in html and "LEDs 10–19</td><td>snake-shelf" in html
    theme = sites["houseplants"].theme
    order = [html.index(f"<strong>{theme['statuses'][s]['label']}</strong>") for s in theme["priority"]]
    assert order == sorted(order)                       # listed in the order the strip prioritises them
    assert "Refill the reservoir. Watering is blocked until you do." in html
    assert all("label" in s and "meaning" in s for s in theme["statuses"].values())


def test_command_writes_all_documents_and_reports_power_warnings(tmp_path, capsys):
    assert main(["docs", "build", str(find_repo_root() / "sites/examples/mushrooms"), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bom.csv", "build-guide.html", "checklist.html", "legend.html",
                                                          "wiring-fruiting-node.svg", "wiring-incubation-node.svg"]
    assert "warning: node fruiting-node: 12 V rail: current of fr-heater, fr-light is not in the catalog" in out


def test_build_returns_what_it_wrote(sites, catalog, tmp_path):
    written = build(sites["microgreens"], catalog, tmp_path / "docs")
    assert all(p.exists() and p.stat().st_size > 200 for p in written) and len(written) == 5
