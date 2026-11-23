"""Load and validate the catalog and site files.

Every YAML file is checked against its JSON Schema (schemas/<kind>.schema.json), then
cross-references are checked (a device's model exists, a zone's devices exist, ...).
All problems are collected and reported together in one ConfigError.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .durations import seconds
from .pins import check_node
from .recipes import resolve_recipe

KINDS = {
    "Component": "components", "Model": "models", "Board": "boards", "Species": "species",
    "Recipe": "recipes", "Goal": "goals", "Theme": "themes",
}
SAFETY_DEFAULTS = {
    "sensor_stale_after": "10m",   # a reading older than this is not trusted
    "reservoir_min_percent": 10,   # pumps are blocked below this level
    "actuator_lease": "3m",        # an on-command expires on the node after this long
    "status_hold": "5m",           # a target must be out of band this long before it shows
}


RETENTION_DEFAULTS = {
    "raw_readings": "30d",         # raw samples older than this are deleted; rollups are kept
    "decision_trace": "14d",       # decision trace and command log older than this are deleted
}


DETECT_DEFAULTS = {
    "ack_within": "60s",            # an actuator that has not acknowledged a command by then is faulty
    "dose_effect_within": "45m",    # a dose must have changed its quantity by then
    "dose_min_change": 1.0,         # ... by at least this much (in the quantity's unit)
    "ineffective_after": "2h",      # a heater or humidifier wanted on this long must have made progress
    "progress_min": 0.5,            # ... of at least this much
    "stuck_after": "12h",           # a sensor repeating one value this long is stuck
    "leak_window": "6h",            # the reservoir must not fall ...
    "leak_drop": 5.0,               # ... this many points in that time without any watering
    "flap_window": "1h",            # a node that goes offline ...
    "flap_count": 3,                # ... this often in that time is unstable
}


RESERVED_NODE_IDS = {"zone", "hub", "sim"}


class ConfigError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def find_repo_root(start: Path | None = None) -> Path:
    """The directory holding schemas/ and catalog/: above `start`, else above the working
    directory (an installed package), else above this file (a source checkout)."""
    for origin in ([start] if start else [Path.cwd(), Path(__file__)]):
        here = origin.resolve()
        for parent in [here, *here.parents]:
            if (parent / "schemas").is_dir() and (parent / "catalog").is_dir():
                return parent
    raise FileNotFoundError("could not find a directory containing schemas/ and catalog/")


def _load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class _Schemas:
    def __init__(self, root: Path):
        self._root = root / "schemas"
        self._cache: dict[str, Draft202012Validator] = {}

    def check(self, kind: str, doc: Any, where: str) -> list[str]:
        name = kind.lower()
        if name not in self._cache:
            schema = json.loads((self._root / f"{name}.schema.json").read_text(encoding="utf-8"))
            self._cache[name] = Draft202012Validator(schema)
        problems = []
        for err in sorted(self._cache[name].iter_errors(doc), key=lambda e: list(e.absolute_path)):
            at = "/".join(str(p) for p in err.absolute_path) or "(top level)"
            problems.append(f"{where}: {at}: {err.message}")
        return problems


class Catalog:
    """Everything under catalog/, indexed by kind and id."""

    def __init__(self, root: Path):
        self.root = root
        self.schemas = _Schemas(root)
        self.items: dict[str, dict[str, dict]] = {kind: {} for kind in KINDS}

    @classmethod
    def load(cls, root: Path | None = None) -> "Catalog":
        root = root or find_repo_root()
        cat = cls(root)
        problems: list[str] = []
        for kind, folder in KINDS.items():
            for path in sorted((root / "catalog" / folder).glob("*.yaml")):
                where = str(path.relative_to(root)).replace("\\", "/")
                doc = _load_yaml(path)
                if not isinstance(doc, dict) or doc.get("kind") != kind:
                    problems.append(f"{where}: expected kind: {kind}")
                    continue
                errors = cat.schemas.check(kind, doc, where)
                problems += errors
                if errors:
                    continue
                if doc["id"] != path.stem:
                    problems.append(f"{where}: id {doc['id']!r} must match the file name")
                if doc["id"] in cat.items[kind]:
                    problems.append(f"{where}: duplicate {kind} id {doc['id']!r}")
                cat.items[kind][doc["id"]] = doc
        problems += cat._cross_check()
        if problems:
            raise ConfigError(problems)
        return cat

    def get(self, kind: str, id_: str) -> dict:
        return self.items[kind][id_]

    def _cross_check(self) -> list[str]:
        problems = []
        components = self.items["Component"]
        quantities = {m["quantity"] for c in components.values() for m in c.get("measures", [])}
        for model in self.items["Model"].values():
            for role in model["implements"]:
                if role not in components:
                    problems.append(f"model {model['id']}: implements unknown component {role!r}")
        for recipe in self.items["Recipe"].values():
            rid = recipe["id"]
            if recipe["species"] not in self.items["Species"]:
                problems.append(f"recipe {rid}: unknown species {recipe['species']!r}")
            stages = recipe.get("stages") or [recipe]
            ids = [s.get("id") for s in recipe.get("stages", [])]
            if len(ids) != len(set(ids)):
                problems.append(f"recipe {rid}: stage ids must be unique")
            for stage in stages:
                sid = f"recipe {rid}" + (f" stage {stage['id']}" if "stages" in recipe else "")
                targets = stage.get("targets", {})
                for quantity in targets:
                    if quantity not in quantities:
                        problems.append(f"{sid}: target for unknown quantity {quantity!r}")
                if stage.get("advance", {}).get("mode") == "elapsed" and "typical" not in stage.get("duration", {}):
                    problems.append(f"{sid}: advance mode elapsed needs duration.typical")
                if stage.get("advance", {}).get("mode") == "condition" and "when" not in stage["advance"]:
                    problems.append(f"{sid}: advance mode condition needs advance.when")
                loop_ids = [loop["id"] for loop in stage.get("control", [])]
                if len(loop_ids) != len(set(loop_ids)):
                    problems.append(f"{sid}: control loop ids must be unique")
                for loop in stage.get("control", []):
                    problems += _check_loop(loop, targets, components, f"{sid} loop {loop['id']}")
        theme_problems = []
        for theme in self.items["Theme"].values():
            for status in theme["priority"]:
                if status not in theme["statuses"]:
                    theme_problems.append(f"theme {theme['id']}: priority lists {status!r} but statuses does not define it")
        return problems + theme_problems


def _check_loop(loop: dict, targets: dict, components: dict, where: str) -> list[str]:
    problems = []
    for key in ("actuator", "strategy"):
        if key not in loop:
            problems.append(f"{where}: {key} is required")
    if problems:
        return problems
    if loop["actuator"] not in components or components[loop["actuator"]]["class"] != "actuator":
        problems.append(f"{where}: {loop['actuator']!r} is not an actuator component")
    need = {"dose": ("trigger", "dose"), "hysteresis": ("quantity", "direction"),
            "duty_cycle": ("on_for", "every"), "schedule": ("on_at", "hours")}[loop["strategy"]]
    for key in need:
        if key not in loop:
            problems.append(f"{where}: strategy {loop['strategy']} needs {key}")
    if loop["strategy"] == "hysteresis" and "quantity" in loop:
        if "target" not in targets.get(loop["quantity"], {}):
            problems.append(f"{where}: targets.{loop['quantity']}.target is required for hysteresis")
    if loop["strategy"] == "dose" and "min_interval" not in loop.get("limits", {}):
        problems.append(f"{where}: dose loops need limits.min_interval")
    return problems


# --------------------------------------------------------------------------- site

@dataclass
class Device:
    id: str
    node: str
    model: dict
    roles: list[str]
    raw: dict

    @property
    def cls(self) -> str:
        return self.roles[0].split(".")[0]


@dataclass
class Zone:
    id: str
    kind: str
    role: str | None
    device_ids: list[str]
    indicator: dict | None


@dataclass
class Planting:
    id: str
    zone: str
    species: dict
    recipe: dict          # resolved: {"id", "stages", "layers"}
    raw: dict


@dataclass
class Site:
    id: str
    raw: dict
    timezone: str
    theme: dict
    safety: dict
    retention: dict = field(default_factory=lambda: {k: seconds(v) for k, v in RETENTION_DEFAULTS.items()})
    detection: dict = field(default_factory=lambda: {k: seconds(v) for k, v in DETECT_DEFAULTS.items()})
    devices: dict[str, Device] = field(default_factory=dict)
    zones: dict[str, Zone] = field(default_factory=dict)
    plantings: dict[str, Planting] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)               # worth a look, but the site loads
    pin_proposals: dict[str, dict[str, str]] = field(default_factory=dict)   # device -> signal -> pin, for blanks
    pin_unassigned: list[str] = field(default_factory=list)         # signals no clean pin is left for

    @property
    def nodes(self) -> list[str]:
        return [n["id"] for n in self.raw["nodes"]]

    def zone_devices(self, zone_id: str, role: str | None = None, cls: str | None = None) -> list[Device]:
        out = []
        for dev_id in self.zones[zone_id].device_ids:
            dev = self.devices[dev_id]
            if role and role not in dev.roles:
                continue
            if cls and not any(r.startswith(cls + ".") for r in dev.roles):
                continue
            out.append(dev)
        return out

    def zones_of_device(self, device_id: str) -> list[str]:
        return [z.id for z in self.zones.values() if device_id in z.device_ids]


def load_site(path: Path | str, catalog: Catalog) -> Site:
    path = Path(path)
    if path.is_dir():
        path = path / "site.yaml"
    where = path.name
    raw = _load_yaml(path)
    problems = catalog.schemas.check("Site", raw, where)
    if problems:
        raise ConfigError(problems)

    models, boards = catalog.items["Model"], catalog.items["Board"]
    theme_id = raw.get("theme", "default")
    if theme_id not in catalog.items["Theme"]:
        problems.append(f"{where}: unknown theme {theme_id!r}")
        raise ConfigError(problems)
    safety_raw = {**SAFETY_DEFAULTS, **raw.get("safety", {})}
    safety = {
        "sensor_stale_after": seconds(safety_raw["sensor_stale_after"]),
        "reservoir_min_percent": float(safety_raw["reservoir_min_percent"]),
        "actuator_lease": seconds(safety_raw["actuator_lease"]),
        "status_hold": seconds(safety_raw["status_hold"]),
    }
    site = Site(id=raw["id"], raw=raw, timezone=raw.get("timezone", "UTC"),
                theme=catalog.items["Theme"][theme_id], safety=safety,
                retention={k: seconds(v) for k, v in {**RETENTION_DEFAULTS, **raw.get("retention", {})}.items()},
                detection={k: seconds(v) for k, v in {**DETECT_DEFAULTS, **raw.get("detection", {})}.items()})

    for node in raw["nodes"]:
        if node["id"] in RESERVED_NODE_IDS:
            problems.append(f"{where}: node id {node['id']!r} is reserved (it would collide with hub topics)")
        if node["board"] not in boards:
            problems.append(f"{where}: node {node['id']}: unknown board {node['board']!r}")
        elif node["runtime"] != "sim" and node["runtime"] not in boards[node["board"]].get("runtimes", []):
            problems.append(f"{where}: node {node['id']}: board {node['board']} does not list runtime {node['runtime']!r}")
        for dev in node["devices"]:
            did = dev["id"]
            if did in site.devices:
                problems.append(f"{where}: device id {did!r} is used more than once")
                continue
            if dev["model"] not in models:
                problems.append(f"{where}: device {did}: unknown model {dev['model']!r}")
                continue
            model = models[dev["model"]]
            roles = dev["as"] if isinstance(dev["as"], list) else [dev["as"]]
            for role in roles:
                if role not in model["implements"]:
                    problems.append(f"{where}: device {did}: model {model['id']} does not implement {role!r}")
            runtimes = {d["runtime"] for d in model["drivers"]}
            if node["runtime"] not in runtimes:
                problems.append(f"{where}: device {did}: model {model['id']} has no {node['runtime']} driver")
            if "actuator.pump" in roles and "flow_ml_per_s" not in dev:
                problems.append(f"{where}: device {did}: pumps need flow_ml_per_s so volumes can be dosed")
            if "indicator.led_strip" in roles and "led_count" not in dev:
                problems.append(f"{where}: device {did}: LED strips need led_count")
            site.devices[did] = Device(id=did, node=node["id"], model=model, roles=roles, raw=dev)
        if node["board"] in boards:
            report = check_node(node["id"], boards[node["board"]],
                                [d for d in site.devices.values() if d.node == node["id"]])
            problems += [f"{where}: {p}" for p in report.problems]
            site.warnings += report.warnings
            site.pin_proposals.update(report.proposals)
            site.pin_unassigned += report.unassigned

    claimed: dict[str, list[tuple[int, int, str]]] = {}
    for zone in raw["zones"]:
        zid = zone["id"]
        if zid in site.zones:
            problems.append(f"{where}: zone id {zid!r} is used more than once")
        for dev_id in zone["devices"]:
            if dev_id not in site.devices:
                problems.append(f"{where}: zone {zid}: unknown device {dev_id!r}")
        indicator = zone.get("indicator")
        if indicator:
            strip = site.devices.get(indicator["strip"])
            first, last = indicator["leds"]
            if strip is None or "indicator.led_strip" not in strip.roles:
                problems.append(f"{where}: zone {zid}: indicator strip {indicator['strip']!r} is not an LED strip device")
            elif first > last or last >= strip.raw.get("led_count", 0):
                problems.append(f"{where}: zone {zid}: leds {indicator['leds']} are outside strip {strip.id} (0..{strip.raw.get('led_count', 0) - 1})")
            else:
                for a, b, other in claimed.setdefault(strip.id, []):
                    if first <= b and a <= last:
                        problems.append(f"{where}: zone {zid}: leds {indicator['leds']} overlap zone {other} on strip {strip.id}")
                claimed[strip.id].append((first, last, zid))
        site.zones[zid] = Zone(id=zid, kind=zone["kind"], role=zone.get("role"),
                               device_ids=[d for d in zone["devices"] if d in site.devices], indicator=indicator)

    for dev in site.devices.values():
        if dev.cls == "actuator" and len(site.zones_of_device(dev.id)) > 1:
            problems.append(f"{where}: actuator {dev.id} is in more than one zone ({', '.join(site.zones_of_device(dev.id))}); "
                            "two recipes would fight over it")

    occupied: dict[str, str] = {}
    roles_available = {z.role for z in site.zones.values() if z.role}
    for planting in raw.get("plantings", []):
        pid = planting["id"]
        ok = True
        for kind, key in (("Species", "species"), ("Recipe", "recipe"), ("Goal", "goal")):
            if key in planting and planting[key] not in catalog.items[kind]:
                problems.append(f"{where}: planting {pid}: unknown {key} {planting[key]!r}")
                ok = False
        if planting["zone"] not in site.zones:
            problems.append(f"{where}: planting {pid}: unknown zone {planting['zone']!r}")
            ok = False
        if not ok:
            continue
        if planting["zone"] in occupied:
            problems.append(f"{where}: planting {pid}: zone {planting['zone']} already holds {occupied[planting['zone']]}")
        occupied[planting["zone"]] = pid
        recipe = catalog.get("Recipe", planting["recipe"])
        species = catalog.get("Species", planting["species"])
        if recipe["species"] != species["id"]:
            problems.append(f"{where}: planting {pid}: recipe {recipe['id']} is for {recipe['species']}, not {species['id']}")
        goal = catalog.get("Goal", planting["goal"]) if "goal" in planting else None
        resolved = resolve_recipe(recipe, species, goal, planting.get("overrides"))
        zone = site.zones[planting["zone"]]
        first_role = resolved["stages"][0].get("zone_role")
        if first_role and zone.role != first_role:
            problems.append(f"{where}: planting {pid}: first stage needs a zone with role {first_role!r}, but {zone.id} has role {zone.role!r}")
        for stage in resolved["stages"]:
            role = stage.get("zone_role")
            if role and role not in roles_available:
                problems.append(f"{where}: planting {pid}: stage {stage['id']} needs a zone with role {role!r}; the site has none")
                continue
            # Every loop needs its actuator in each zone the stage can run in.
            candidates = [z for z in site.zones.values() if z.role == role] if role else [zone]
            for loop in stage["control"]:
                for cand in candidates:
                    if not site.zone_devices(cand.id, role=loop["actuator"]):
                        problems.append(f"{where}: planting {pid}: stage {stage['id']} loop {loop['id']} needs {loop['actuator']} in zone {cand.id}")
        site.plantings[pid] = Planting(id=pid, zone=planting["zone"], species=species, recipe=resolved, raw=planting)

    if problems:
        raise ConfigError(problems)
    return site
