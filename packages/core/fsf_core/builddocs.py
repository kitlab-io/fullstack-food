"""Build documents generated from a site file and the catalog, so they cannot drift from
what the hub runs:

    fsf docs build sites/local/my-site      ->  build/docs/<site>/

    bom.csv              everything to buy: boards, parts, the support parts each needs, supplies
    wiring-<node>.svg    which pin goes where, per node
    build-guide.html     safety, parts, power, then one step per device, each ending in a test
    checklist.html       the commissioning stages to tick off, printable
    legend.html          what each LED segment and colour means, printable

Electrical values come from catalog/models and are only as good as those entries: a model
with `datasheet_checked: false` is marked as unconfirmed in every document.
"""

from __future__ import annotations

import csv
import io
import math
from html import escape
from pathlib import Path

from .catalog import Catalog, Device, Site

RAILS = {"3v3": "3.3 V", "5v": "5 V", "12v": "12 V", "mains": "mains"}
HEADROOM = 1.3              # supplies are sized for the peak plus this margin
BOARD_5V_LIMIT_MA = 500     # above this a 5 V load must not be fed through the board
SIGNAL_COLOR = {"i2c_sda": "#1f6f8b", "i2c_scl": "#7a4fb5", "adc": "#b5651d", "digital_in": "#2e7d50",
                "digital_out": "#c2331a", "pwm": "#c2331a", "onewire": "#2e7d50", "led_data": "#b8860b"}
SAFETY_RULES = [
    ("mains", "Mains loads are switched only through a certified smart plug or an enclosed, rated relay module. "
              "No exposed mains wiring."),
    ("water", "Electronics sit above and away from water. Every cable gets a drip loop. The reservoir stands lower "
              "than the electronics, and pump outlets are arranged so a stopped pump cannot siphon."),
    ("heat", "A heater is always in a zone with a temperature sensor and a recipe max_on limit. Keep heating "
             "elements off plastic and substrate bags."),
    ("12v", "Fuse each 12 V rail. Fit flyback protection on pumps and fans. Join the grounds of all supplies."),
    ("led", "LED strips: level-shift the data line from 3.3 V, put a series resistor on it and a bulk capacitor "
            "across the supply at the strip, and inject power on long strips."),
]


def _node_devices(site: Site, node_id: str) -> list[Device]:
    return [d for d in site.devices.values() if d.node == node_id]


def _unconfirmed(model: dict) -> bool:
    return model.get("datasheet_checked") is False


# --------------------------------------------------------------------------- power

def power_budget(site: Site, catalog: Catalog) -> list[dict]:
    """Per node and rail: typical and peak current, what could not be counted, and warnings."""
    out = []
    for node in site.raw["nodes"]:
        rails: dict[str, dict] = {}
        warnings: list[str] = []
        for dev in _node_devices(site, node["id"]):
            power = dev.model.get("power")
            if power is None:
                warnings.append(f"{dev.id}: the catalog has no power data for {dev.model['id']}")
                continue
            rail = rails.setdefault(power["rail"], {"typical_ma": 0.0, "peak_ma": 0.0, "unknown": [], "loads": []})
            count = dev.raw.get("led_count", 1) if power.get("per") == "led" else 1
            if "peak_ma" not in power:
                rail["unknown"].append(dev.id)
                rail["loads"].append({"device": dev.id, "peak_ma": None, "note": power.get("notes", "")})
                continue
            rail["typical_ma"] += power.get("typical_ma", power["peak_ma"]) * count
            rail["peak_ma"] += power["peak_ma"] * count
            rail["loads"].append({"device": dev.id, "peak_ma": power["peak_ma"] * count,
                                  "note": f"{count} LEDs" if count > 1 else ""})
        for name, rail in rails.items():
            if name in ("5v", "12v"):
                rail["supply_a"] = math.ceil(rail["peak_ma"] * HEADROOM / 500) / 2 if rail["peak_ma"] else None
            if rail["unknown"] and name != "mains":
                warnings.append(f"{RAILS[name]} rail: current of {', '.join(rail['unknown'])} is not in the catalog; "
                                "measure it and add it before choosing a supply")
        if rails.get("5v", {}).get("peak_ma", 0) > BOARD_5V_LIMIT_MA:
            warnings.append(f"5 V rail peaks at {rails['5v']['peak_ma'] / 1000:.1f} A: feed it from its own supply, "
                            "not through the board's 5 V pin or USB port")
        out.append({"node": node["id"], "board": node["board"], "rails": rails, "warnings": warnings})
    return out


# --------------------------------------------------------------------------- bill of materials

def bom(site: Site, catalog: Catalog) -> list[dict]:
    """Rows of {category, item, qty, used_by, note}: boards, parts, support parts, supplies."""
    rows: dict[tuple[str, str, str], dict] = {}

    def add(category: str, item: str, qty: int, used_by: str, note: str = "") -> None:
        row = rows.setdefault((category, item, note), {"category": category, "item": item, "qty": 0, "used_by": [], "note": note})
        row["qty"] += qty
        if used_by not in row["used_by"]:
            row["used_by"].append(used_by)

    for node in site.raw["nodes"]:
        board = catalog.get("Board", node["board"])
        add("board", board.get("name", board["id"]), 1, node["id"])
        once: set[tuple[str, str]] = set()
        for dev in _node_devices(site, node["id"]):
            model = dev.model
            add("part", model.get("name", model["id"]), 1, dev.id,
                "values not yet confirmed against the datasheet" if _unconfirmed(model) else "")
            for support in model.get("wiring", []):
                key = (support["part"], support["purpose"])
                if "when" in support:           # conditional parts are per node, not per device (shared bus, shared rail)
                    if key in once:
                        continue
                    once.add(key)
                    add("support", support["part"], support.get("qty", 1), node["id"], f"{support['purpose']}; only if {support['when']}")
                else:
                    add("support", support["part"], support.get("qty", 1), dev.id, support["purpose"])
    for entry in power_budget(site, catalog):
        for name in ("5v", "12v"):
            rail = entry["rails"].get(name)
            if rail is None:
                continue
            size = f"at least {rail['supply_a']:g} A" if rail.get("supply_a") else "size after measuring the loads"
            note = f"peak {rail['peak_ma'] / 1000:.2f} A plus {round((HEADROOM - 1) * 100)} % margin" if rail.get("supply_a") else ""
            if rail["unknown"]:
                note = (note + "; " if note else "") + f"not counted: {', '.join(rail['unknown'])}"
            add("supply", f"{RAILS[name]} power supply, {size}", 1, entry["node"], note)
    order = {"board": 0, "part": 1, "support": 2, "supply": 3}
    return sorted(({**r, "used_by": ", ".join(r["used_by"])} for r in rows.values()),
                  key=lambda r: (order[r["category"]], r["item"]))


def bom_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["category", "item", "qty", "used_by", "note"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


# --------------------------------------------------------------------------- wiring diagram

def wiring_svg(site: Site, catalog: Catalog, node_id: str) -> str:
    """Board pins on the left, devices on the right, one line per signal."""
    node = next(n for n in site.raw["nodes"] if n["id"] == node_id)
    board = catalog.get("Board", node["board"])
    devices = _node_devices(site, node_id)
    pins: list[str] = []
    for dev in devices:
        for pin in dev.raw.get("pins", {}).values():
            if "/" not in pin and pin not in pins:
                pins.append(pin)
    order = list(board.get("pins", {}))
    pins.sort(key=lambda p: order.index(p) if p in order else len(order))

    row, top, board_x, board_w, dev_x, dev_w = 26, 70, 30, 190, 470, 400
    pin_y = {pin: top + 46 + i * row for i, pin in enumerate(pins)}
    board_h = 62 + max(1, len(pins)) * row
    parts: list[str] = []
    lines: list[str] = []
    y = top
    for dev in devices:
        signals = dev.model.get("pins", [])
        support = dev.model.get("wiring", [])
        power = dev.model.get("power", {})
        mains = dev.model["interface"]["bus"] == "mains_relay"
        height = 54 + len(signals) * 22 + (18 if support else 0) + (20 if mains else 0)
        parts.append(f'<rect class="box{" mains" if mains else ""}" x="{dev_x}" y="{y}" width="{dev_w}" height="{height}" rx="8"/>')
        parts.append(f'<text class="title" x="{dev_x + 12}" y="{y + 20}">{escape(dev.id)}</text>')
        rail = RAILS.get(power.get("rail"), "?")
        parts.append(f'<text class="small" x="{dev_x + 12}" y="{y + 36}">{escape(dev.model.get("name", dev.model["id"]))} · {rail}</text>')
        line_y = y + 56
        for signal in signals:
            pin = dev.raw.get("pins", {}).get(signal["signal"])
            color = SIGNAL_COLOR.get(signal["needs"], "#555")
            label = signal["signal"] + (f" ({signal['level_v']:g} V!)" if "level_v" in signal else "")
            if pin is None:
                parts.append(f'<text class="warn" x="{dev_x + 12}" y="{line_y + 4}">{escape(label)}: no pin assigned</text>')
            elif "/" in pin:
                provider, channel = pin.split("/")
                parts.append(f'<text class="sig" x="{dev_x + 12}" y="{line_y + 4}" fill="{color}">{escape(label)} → {escape(provider)} channel {escape(channel)}</text>')
            else:
                parts.append(f'<circle cx="{dev_x}" cy="{line_y}" r="4" fill="{color}"/>')
                parts.append(f'<text class="sig" x="{dev_x + 12}" y="{line_y + 4}" fill="{color}">{escape(label)} ← {escape(pin)}</text>')
                x1, y1, mid = board_x + board_w, pin_y[pin], (board_x + board_w + dev_x) / 2
                lines.append(f'<path d="M{x1} {y1} C{mid} {y1} {mid} {line_y} {dev_x} {line_y}" stroke="{color}"/>')
            line_y += 22
        if mains:
            where = (f"Mains: outlet {dev.raw['outlet']} of this strip." if "outlet" in dev.raw
                     else "Mains: through a certified smart plug. No board wiring.")
            parts.append(f'<text class="warn" x="{dev_x + 12}" y="{line_y + 4}">{where}</text>')
            line_y += 20
        if support:
            names = ", ".join(f"{s.get('qty', 1)}× {s['part']}" for s in support)
            shown = names if len(names) <= 62 else names[:59] + "…"
            parts.append(f'<text class="small" x="{dev_x + 12}" y="{line_y + 4}">needs: {escape(shown)}</text>')
        y += height + 14
    height = max(y, top + board_h) + 46
    board_svg = [f'<rect class="box board" x="{board_x}" y="{top}" width="{board_w}" height="{board_h}" rx="8"/>',
                 f'<text class="title" x="{board_x + 12}" y="{top + 20}">{escape(node_id)}</text>',
                 f'<text class="small" x="{board_x + 12}" y="{top + 36}">{escape(board.get("name", board["id"]))}</text>']
    for pin, py in pin_y.items():
        caution = board.get("pins", {}).get(pin, {}).get("caution")
        board_svg.append(f'<circle cx="{board_x + board_w}" cy="{py}" r="4" fill="#333"/>')
        board_svg.append(f'<text class="{"warn" if caution else "sig"}" x="{board_x + board_w - 12}" y="{py + 4}" text-anchor="end">'
                         f'{escape(pin)}{" (caution)" if caution else ""}</text>')
    if not pins:
        board_svg.append(f'<text class="small" x="{board_x + 12}" y="{top + 56}">no pins in use</text>')
    note = ("Signal wires only. Every part also needs its supply rail and ground; support parts are listed in the guide."
            + (" Values not yet confirmed against datasheets." if any(_unconfirmed(d.model) for d in devices) else ""))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 {height}" width="900" height="{height}" role="img" '
            f'aria-label="Wiring of node {escape(node_id)}">\n'
            '<style>text{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;fill:#1c2420}.title{font-size:14px;font-weight:600}'
            '.small{font-size:11px;fill:#5d6a63}.sig{font-size:12px}.warn{font-size:12px;fill:#a4460f;font-weight:600}'
            '.box{fill:#fff;stroke:#b9c2bc}.board{fill:#eef2ee}.mains{stroke:#a4460f;stroke-dasharray:6 4}'
            'path{fill:none;stroke-width:2}</style>\n'
            f'<rect width="900" height="{height}" fill="#f7f8f5"/>\n'
            f'<text class="title" x="30" y="32">Wiring: {escape(site.id)} / {escape(node_id)}</text>\n'
            f'<text class="small" x="30" y="50">{escape(note)}</text>\n'
            + "\n".join(lines + board_svg + parts) + "\n</svg>\n")


# --------------------------------------------------------------------------- HTML documents

CSS = """
body{font:16px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;color:#1c2420;background:#fff;max-width:60rem;margin:0 auto;padding:1.5rem}
h1{font-size:1.6rem;margin:0 0 .25rem}h2{font-size:1.2rem;margin:2rem 0 .5rem;border-bottom:1px solid #dfe4df;padding-bottom:.25rem}
h3{font-size:1rem;margin:1.25rem 0 .25rem}p,ul,ol{margin:.4rem 0}.muted{color:#5d6a63}.small{font-size:.85rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border:1px solid #dfe4df;padding:.35rem .5rem;text-align:left;vertical-align:top}
th{background:#f4f5f1}.warn{background:#fdf1e7;color:#8a3a0c;border-radius:.4rem;padding:.5rem .75rem;margin:.5rem 0}
.step{border:1px solid #dfe4df;border-radius:.5rem;padding:.75rem 1rem;margin:.75rem 0;break-inside:avoid}
.test{background:#eef5f0;border-radius:.4rem;padding:.4rem .6rem;margin-top:.5rem}code{background:#f4f5f1;padding:.05rem .3rem;border-radius:.25rem}
svg{max-width:100%;height:auto}.box{display:inline-block;width:1.1rem;height:1.1rem;border:1.5px solid #1c2420;border-radius:.2rem;vertical-align:middle}
.swatch{display:inline-block;width:2.2rem;height:1.1rem;border-radius:.3rem;border:1px solid #9aa8a0;vertical-align:middle}
@media print{body{padding:0}h2{break-after:avoid}}
"""


def _page(title: str, body: str) -> str:
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{escape(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _power_html(budget: list[dict]) -> str:
    out = []
    for entry in budget:
        rows = []
        for name, rail in entry["rails"].items():
            if name == "mains":
                rows.append([RAILS[name], "–", "–", "wattage is on each appliance's label", escape(", ".join(rail["unknown"]))])
                continue
            supply = "from the board" if name == "3v3" else f"{rail['supply_a']:g} A or more" if rail.get("supply_a") else "after measuring"
            loads = ", ".join(f"{ld['device']} {ld['peak_ma']:g} mA" if ld["peak_ma"] is not None else f"{ld['device']} unknown"
                              for ld in rail["loads"])
            rows.append([RAILS[name], f"{rail['typical_ma']:g} mA", f"{rail['peak_ma']:g} mA", supply, escape(loads)])
        out.append(f"<h3>{escape(entry['node'])}</h3>" + _table(["Rail", "Typical", "Peak", "Supply", "Loads at peak"], rows))
        out += [f'<p class="warn">{escape(w)}</p>' for w in entry["warnings"]]
    return "\n".join(out)


def build_guide_html(site: Site, catalog: Catalog) -> str:
    hazards = {h for d in site.devices.values() for h in d.model.get("safety", {}).get("hazards", [])}
    rails = {d.model.get("power", {}).get("rail") for d in site.devices.values()}
    has_strip = any("indicator.led_strip" in d.roles for d in site.devices.values())
    rules = [text for key, text in SAFETY_RULES
             if key in hazards or (key == "12v" and "12v" in rails) or (key == "led" and has_strip)]
    unconfirmed = sorted({d.model["id"] for d in site.devices.values() if _unconfirmed(d.model)})
    body = [f"<h1>Build guide: {escape(site.raw.get('name', site.id))}</h1>",
            f'<p class="muted">Generated from the site file <code>{escape(site.id)}</code> and the catalog. '
            "Change those and build again rather than editing this page.</p>"]
    if unconfirmed:
        body.append('<p class="warn"><strong>Not yet confirmed on hardware.</strong> Pins, wiring, support parts and currents for '
                    f"these parts are from general experience, not checked against their datasheets: {escape(', '.join(unconfirmed))}. "
                    "Check each against its datasheet before you power it.</p>")
    body.append("<h2>1. Safety</h2><ul>" + "".join(f"<li>{escape(r)}</li>" for r in rules) + "</ul>")
    notes = sorted({f"{d.id}: {d.model['safety']['notes']}" for d in site.devices.values() if d.model.get("safety", {}).get("notes")})
    if notes:
        body.append("<ul class='small'>" + "".join(f"<li>{escape(n)}</li>" for n in notes) + "</ul>")
    rows = bom(site, catalog)
    body.append("<h2>2. Parts</h2>" + _table(["", "Item", "Qty", "For", "Note"], [
        [escape(r["category"]), escape(r["item"]), str(r["qty"]), escape(r["used_by"]), escape(r["note"])] for r in rows]))
    body.append("<h2>3. Power</h2>" + _power_html(power_budget(site, catalog)))

    body.append("<h2>4. Build, one step at a time</h2><p>Finish each step with its test before starting the next. "
                "The tests need the hub and the broker running; a failed test is recorded too.</p>")
    step = 0
    for node in site.raw["nodes"]:
        devices = _node_devices(site, node["id"])
        body.append(f"<h3>Node {escape(node['id'])}</h3>{wiring_svg(site, catalog, node['id'])}")
        step += 1
        strip = catalog.get("Board", node["board"])["class"] == "smart_plug"
        if strip:
            body.append(f'<div class="step"><strong>Step {step}. Set up the power strip.</strong> Join it to the network with its own app, give it a '
                        "fixed address on your router, and start the bridge on the hub host with nothing plugged in. "
                        '<p class="warn">The strip cannot end an on-command by itself: the bridge switches each outlet off when its lease '
                        "runs out. If the bridge stops while an outlet is on, the outlet stays on until the bridge is back. Run the bridge under "
                        "a supervisor that restarts it, and keep max_on short for anything that heats.</p>"
                        f'<div class="test">Test: <code>FSF_KASA_HOST=&lt;address&gt; python -m fsf_kasa --site &lt;site&gt; --node {escape(node["id"])}</code>, '
                        "then the node appears as online on the dashboard's devices page.</div></div>")
        else:
            body.append(f'<div class="step"><strong>Step {step}. Flash the bare board.</strong> Build the firmware and flash it over USB '
                        "before anything is connected to the board."
                        f'<div class="test">Test: <code>fsf firmware build &lt;site&gt;</code>, <code>fsf firmware flash &lt;site&gt; {escape(node["id"])}</code>, '
                        "then the node appears as online on the dashboard's devices page.</div></div>")
        # A part others plug into comes first, then sensors, then actuators, so every actuator
        # is first tried with something watching.
        for dev in sorted(devices, key=lambda d: ("provides" not in d.model, d.cls == "actuator", d.cls == "indicator")):
            step += 1
            model = dev.model
            pins = dev.raw.get("pins", {})
            signals = ", ".join(f"{s['signal']} to {pins.get(s['signal'], 'NOT ASSIGNED')}" for s in model.get("pins", []))
            connect = (f"Connect {signals}." if signals else
                       f"Plug it into outlet {dev.raw['outlet'] + 1} of the strip (outlet {dev.raw['outlet']} in the site file)." if "outlet" in dev.raw
                       else "Plug it into its smart plug. It has no wiring to the board." if model["interface"]["bus"] == "mains_relay"
                       else "No signal wiring.")
            rail = RAILS.get(model.get("power", {}).get("rail"), "its supply")
            support = "".join(f"<li>{s.get('qty', 1)}× {escape(s['part'])}: {escape(s['purpose'])}"
                              + (f" <span class='muted'>(only if {escape(s['when'])})</span>" if "when" in s else "") + "</li>"
                              for s in model.get("wiring", []))
            bench = model.get("bench_test")
            test = (f"Test: <code>fsf bench {escape(dev.id)} --site &lt;site&gt;</code>. {escape(bench['stimulus'])}. "
                    f"Expected: {escape(bench['expect'])}." if bench else "No bench test is defined for this part yet.")
            cal = model.get("calibration")
            calibrate = (f'<div class="test">Then calibrate: <code>fsf calibrate {escape(dev.id)} --site &lt;site&gt;</code>. '
                         f"{escape(cal.get('notes', ''))}</div>" if cal and cal["procedure"] != "co2_fresh_air" else "")
            body.append(f'<div class="step"><strong>Step {step}. {escape(dev.id)}</strong> <span class="muted">({escape(model.get("name", model["id"]))})</span>'
                        f"<p>Power off first. {escape(connect)} Supply: {escape(rail)} and ground.</p>"
                        + (f"<ul>{support}</ul>" if support else "")
                        + f'<div class="test">{test}</div>{calibrate}</div>')
        step += 1
        body.append(f'<div class="step"><strong>Step {step}. Node acceptance.</strong> With everything on the node connected.'
                    f'<div class="test">Test: <code>fsf node test {escape(node["id"])} --site &lt;site&gt; --actuate --last-will</code>. '
                    "Every check must pass: reports, lease expiry, off, and offline when unplugged.</div></div>")
    for zone in site.zones.values():
        step += 1
        body.append(f'<div class="step"><strong>Step {step}. Zone {escape(zone.id)}.</strong> Leave the zone in observe mode for a day and '
                    "read what the hub would have done on its dashboard page. Then run the shortened acceptance, and only then switch it to active."
                    f'<div class="test">Test: <code>fsf zone test {escape(zone.id)} --site &lt;site&gt;</code>, then '
                    f"<code>fsf zone mode {escape(zone.id)} active --site &lt;site&gt;</code>. Watch it for two days.</div></div>")
    return _page(f"Build guide: {site.id}", "\n".join(body))


def checklist_html(site: Site, catalog: Catalog) -> str:
    box = '<span class="box"></span>'
    body = [f"<h1>Commissioning checklist: {escape(site.raw.get('name', site.id))}</h1>",
            '<p class="muted">Tick each box when the command has passed. The hub keeps the same record: <code>fsf commissioning --site &lt;site&gt;</code>.</p>']
    for node in site.raw["nodes"]:
        rows = []
        for dev in _node_devices(site, node["id"]):
            cal = dev.model.get("calibration")
            rows.append([escape(dev.id), escape(dev.model.get("name", dev.model["id"])),
                         f"{box} <code>fsf bench {escape(dev.id)}</code>" if dev.model.get("bench_test") else "–",
                         f"{box} <code>fsf calibrate {escape(dev.id)}</code>" if cal and cal["procedure"] != "co2_fresh_air" else "–"])
        body.append(f"<h2>Node {escape(node['id'])}</h2>" + _table(["Device", "Part", "1. Bench", "2. Calibration"], rows)
                    + f"<p>{box} 3. Node acceptance: <code>fsf node test {escape(node['id'])} --actuate --last-will</code></p>")
    rows = [[escape(z.id), f"{box} 24 h in observe mode, decisions reviewed", f"{box} <code>fsf zone test {escape(z.id)}</code>",
             f"{box} switched to active, 48 h without unexplained events"] for z in site.zones.values()]
    body.append("<h2>Zones</h2>" + _table(["Zone", "4. Dry run", "5. Acceptance", "6. Soak"], rows))
    body.append('<p class="small muted">Date and name: ______________________________</p>')
    return _page(f"Commissioning checklist: {site.id}", "\n".join(body))


def _css_color(rgbw: list[int]) -> str:
    """An LED colour as it reads on paper or screen (LED levels are dim on purpose)."""
    r, g, b, w = rgbw
    mixed = [min(255, c + w) for c in (r, g, b)]
    peak = max(mixed)
    if peak < 8:
        return "#ffffff"
    return "rgb(" + ",".join(str(round(c * 225 / peak)) for c in mixed) + ")"


def legend_html(site: Site, catalog: Catalog) -> str:
    theme = site.theme
    body = [f"<h1>Status lights: {escape(site.raw.get('name', site.id))}</h1>"]
    strips: dict[str, list] = {}
    for zone in site.zones.values():
        if zone.indicator:
            strips.setdefault(zone.indicator["strip"], []).append((zone.indicator["leds"], zone.id))
    for strip, segments in strips.items():
        rows = [[f"LEDs {first}–{last}", escape(zone_id)] for (first, last), zone_id in sorted(segments)]
        body.append(f"<h2>Strip {escape(strip)}</h2>" + _table(["Segment (counted from the plug end, starting at 0)", "Zone"], rows))
    if not strips:
        body.append("<p>This site has no status strip.</p>")
    effects = {"solid": "steady", "breathe": "slowly fading in and out", "blink": "blinking once a second",
               "blink_slow": "blinking slowly", "off": "dark"}
    rows = []
    for status in theme["priority"]:
        style = theme["statuses"][status]
        rows.append([f'<span class="swatch" style="background:{_css_color(style["color"])}"></span>', escape(effects[style["effect"]]),
                     f"<strong>{escape(style.get('label', status.replace('_', ' ')))}</strong>", escape(style.get("meaning", ""))])
    body.append("<h2>What a segment is telling you</h2><p class='muted'>When several things are true at once, the one highest in this "
                "list is shown.</p>" + _table(["Colour", "Light is", "Status", "What it means and what to do"], rows))
    night = theme["brightness"]["night_hours"]
    body.append(f"<p class='small muted'>Lights dim between {night[0]}:00 and {night[1]}:00. Colours on paper are approximate.</p>")
    return _page(f"Status lights: {site.id}", "\n".join(body))


RUNTIMES = ("esphome", "kasa", "linux", "circuitpython", "sim")
STATUS_WORDS = {"verified": "verified", "bench": "run by hand", "untested": "untested"}


def compatibility(catalog: Catalog) -> dict:
    """What has actually been tried: per part and runtime, the driver's status and where it was verified."""
    parts = []
    for model in sorted(catalog.items["Model"].values(), key=lambda m: m.get("name", m["id"])):
        drivers = {d["runtime"]: d for d in model["drivers"]}
        parts.append({"id": model["id"], "name": model.get("name", model["id"]), "implements": model["implements"],
                      "datasheet_checked": model.get("datasheet_checked"),
                      "drivers": {rt: {"status": drivers[rt]["status"], "tested_on": drivers[rt].get("tested_on", [])}
                                  for rt in RUNTIMES if rt in drivers}})
    boards = [{"id": b["id"], "name": b.get("name", b["id"]), "class": b["class"], "runtimes": b.get("runtimes", []),
               "os": b.get("os", []), "pin_map": "pins" in b, "datasheet_checked": b.get("datasheet_checked")}
              for b in sorted(catalog.items["Board"].values(), key=lambda b: b["id"])]
    real = [(p["id"], rt) for p in parts for rt, d in p["drivers"].items() if rt != "sim" and d["status"] == "verified"]
    return {"parts": parts, "boards": boards, "verified_on_hardware": real}


def compatibility_markdown(catalog: Catalog) -> str:
    data = compatibility(catalog)
    lines = ["# Compatibility", "", "Generated from catalog/models and catalog/boards. Do not edit.", "",
             "`verified`: passes the test suite on the listed targets. `run by hand`: someone ran it once on a bench. "
             "`untested`: expected to work, never run. The simulated driver being verified says nothing about hardware.", ""]
    if not data["verified_on_hardware"]:
        lines += ["**No part is verified on real hardware yet.**", ""]
    lines += ["## Parts", "", "| Part | " + " | ".join(RUNTIMES) + " | Wiring data checked |", "|---|" + "---|" * (len(RUNTIMES) + 1)]
    for part in data["parts"]:
        cells = []
        for rt in RUNTIMES:
            driver = part["drivers"].get(rt)
            cells.append("–" if driver is None else STATUS_WORDS[driver["status"]]
                         + (f" ({', '.join(driver['tested_on'])})" if driver["tested_on"] else ""))
        checked = {True: "yes", False: "no", None: "no data"}[part["datasheet_checked"]]
        lines.append(f"| {part['name']} | " + " | ".join(cells) + f" | {checked} |")
    lines += ["", "## Boards", "", "| Board | Kind | Runtimes | Operating systems | Pin map |", "|---|---|---|---|---|"]
    for board in data["boards"]:
        pin_map = "–" if board["class"] != "mcu" else ("yes, unconfirmed" if board["pin_map"] and board["datasheet_checked"] is False
                                                       else "yes" if board["pin_map"] else "no")
        lines.append(f"| {board['name']} | {board['class'].replace('_', ' ')} | {', '.join(board['runtimes']) or '–'} | "
                     f"{', '.join(board['os']) or '–'} | {pin_map} |")
    return "\n".join(lines) + "\n"


def compatibility_html(catalog: Catalog) -> str:
    """The same tables as a page."""
    blocks, table, rows = [], False, []
    for line in compatibility_markdown(catalog).splitlines():
        if line.startswith("|"):
            if set(line) <= set("|- "):
                continue
            rows.append([escape(c.strip()) for c in line.strip("|").split("|")])
            table = True
            continue
        if table:
            blocks.append(_table([c for c in rows[0]], rows[1:]))
            table, rows = False, []
        if line.startswith("# "):
            blocks.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            blocks.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("**"):
            blocks.append(f'<p class="warn">{escape(line.strip("*"))}</p>')
        elif line:
            blocks.append(f"<p>{escape(line).replace('`', '')}</p>")
    if rows:
        blocks.append(_table(rows[0], rows[1:]))
    return _page("Compatibility", "\n".join(blocks))


def build(site: Site, catalog: Catalog, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {"bom.csv": bom_csv(bom(site, catalog)), "build-guide.html": build_guide_html(site, catalog),
             "checklist.html": checklist_html(site, catalog), "legend.html": legend_html(site, catalog)}
    for node in site.raw["nodes"]:
        files[f"wiring-{node['id']}.svg"] = wiring_svg(site, catalog, node["id"])
    written = []
    for name, text in files.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written
