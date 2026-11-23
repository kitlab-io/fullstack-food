"""The dashboard's HTTP API and static frontend.

Reads come from the hub's SQLite file, opened read-only for each request, and from what
MQTT says is true right now (live.py). The only thing that changes anything is
POST /api/commands, which publishes an operator command to the hub and returns its reply.
The service never writes to the database and never publishes to device topics.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from jsonschema import Draft202012Validator
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles

from fsf_core import Catalog, Site, find_repo_root, seconds, topics
from fsf_core import troubleshooting
from fsf_core.doctor import redact
from fsf_hub import Store

from .auth import COOKIE, SESSION_S, Auth, LoginError
from .live import Live

OPEN_PATHS = {"/api/login", "/api/session", "/api/health"}
# What a person may do from the dashboard. `commission` is left to the commissioning tools.
ACTIONS = ("advance_stage", "water_now", "set_override", "clear_override", "pause_zone", "resume_zone",
           "actuator_test", "set_zone_mode")

RAW_UP_TO = 12 * 3600           # spans up to this long are served as raw samples
FIVE_MIN_UP_TO = 4 * 86400      # then 5-minute rollups, then hourly
RESOLUTIONS = {"raw": 0, "5m": 300, "1h": 3600}
MAX_POINTS = 20000
LEVELS = ("debug", "info", "warn", "error")
LOG_SCAN = 5000                 # newest rows read from each table before filtering
GROUPS = {"dose": "dose", "stage_advanced": "stage", "planting_started": "stage", "planting_finished": "stage",
          "status_changed": "status", "limit": "limit", "interlock": "interlock", "node_status": "node",
          "bad_payload": "node", "detection": "detection", "detection_cleared": "detection",
          "command": "command", "command_rejected": "command", "command_failed": "command", "actuator_test": "command",
          "override_cleared": "command", "zone_resumed": "command"}


def describe(kind: str, e: dict) -> str:
    """One line a person can read for an event."""
    if kind == "dose":
        how = "by hand" if e.get("by") == "operator" else "automatic"
        return f"{e['device']} dosed {e['volume_ml']:g} ml ({how})" + (", observe mode: not carried out" if e.get("observed") else "")
    if kind == "status_changed":
        return f"status {e.get('was') or 'none'} -> {e['state']}" + (f" (also {', '.join(a for a in e['active'] if a != e['state'])})"
                                                                     if len(e.get("active", [])) > 1 else "")
    if kind == "stage_advanced":
        return f"{e['from_stage']} -> {e['to_stage']} (by {e['by']})"
    if kind == "planting_started":
        return f"started with recipe {e.get('recipe')}"
    if kind == "planting_finished":
        return f"finished (by {e.get('by')})"
    if kind == "limit":
        if e.get("observed"):
            return f"{e['device']} would have hit {e['reason']} (observe mode: nothing was switched)"
        return f"{e['device']} hit {e['reason']} and was switched off"
    if kind == "interlock":
        return f"{e.get('loop')} blocked: {e['reason']}"
    if kind == "node_status":
        return f"node {e['node']} {'online' if e['online'] else 'offline'}"
    if kind == "command":
        return f"{e['command'].get('name')} accepted" + (f" from {e['by']}" if e.get("by") else "")
    if kind == "command_rejected":
        return f"{e['command'].get('name')} rejected: {e['error']}"
    if kind == "command_failed":
        return f"{e['device']} refused a command: {e.get('error')}"
    if kind == "actuator_test":
        return f"test pulse on {e['device']} for {e['duration_s']:g} s"
    if kind == "detection":
        return f"{e['status'].replace('_', ' ')}: {e['detail']}"
    if kind == "detection_cleared":
        return f"{e['status'].replace('_', ' ')} cleared ({e['subject']})"
    if kind == "bad_payload":
        return f"{e['device']} sent a message that is not a JSON object"
    if kind == "override_cleared":
        return f"override on {', '.join(e['quantities'])} ended ({e['reason']})"
    if kind == "zone_resumed":
        return f"resumed ({e['reason']})"
    return kind.replace("_", " ")


def as_file(rows: list[dict], columns: list[str], fmt: str, name: str) -> Response:
    """rows as a JSON Lines or CSV download."""
    if fmt == "jsonl":
        body = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
        media = "application/x-ndjson"
    else:
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([json.dumps(row[c], separators=(",", ":")) if isinstance(row.get(c), (dict, list)) else row.get(c)
                             for c in columns])
        body, media = out.getvalue(), "text/csv"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


def _parse(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"{name} must be an ISO 8601 time") from None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _age(now: datetime, iso: str | None) -> float | None:
    return round((now - datetime.fromisoformat(iso)).total_seconds(), 1) if iso else None


def on_intervals(commands: list[dict]) -> list[list[float]]:
    """[start, end] epoch seconds for each time an actuator was on, from its leased commands."""
    intervals: list[list[float]] = []
    for cmd in commands:
        at = cmd["t"].timestamp()
        if cmd["ok"] is False:
            continue
        if cmd["name"] == "on":
            ends = at + float(cmd["data"].get("duration_s", 0))
            if intervals and at <= intervals[-1][1]:
                intervals[-1][1] = ends                 # a renewal of the running lease
            else:
                intervals.append([at, ends])
        elif cmd["name"] == "off" and intervals and at < intervals[-1][1]:
            intervals[-1][1] = at
    return intervals


def create_app(site: Site, catalog: Catalog, db_path: str, live: Live, static_dir: Path | None = None,
               developer: bool = False, auth: Auth | None = None) -> FastAPI:
    """developer: also allow downloading the whole database. auth: who may read and act
    (default: nobody can log in, so the API is closed)."""
    app = FastAPI(title="Fullstack Food", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    components = catalog.items["Component"]
    auth = auth or Auth()
    command_schema = Draft202012Validator(json.loads(
        (find_repo_root() / "schemas" / "mqtt" / "hub_command.schema.json").read_text(encoding="utf-8")))
    sim_schema = Draft202012Validator(json.loads(
        (find_repo_root() / "schemas" / "mqtt" / "sim_command.schema.json").read_text(encoding="utf-8")))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        session = auth.session(request.cookies.get(COOKIE))
        request.state.session = session
        if path.startswith("/api/") and path not in OPEN_PATHS and not auth.no_login:
            reading = request.method in ("GET", "HEAD")
            if session is None and not (reading and auth.read_without_login):
                return JSONResponse({"detail": "login required"}, status_code=401)
            if not reading and request.headers.get("x-csrf-token") != session["csrf"]:
                return JSONResponse({"detail": "missing or wrong CSRF token"}, status_code=403)
        return await call_next(request)

    @app.get("/api/session")
    def get_session(request: Request) -> dict:
        return auth.describe(request.state.session)

    @app.post("/api/login")
    def login(request: Request, body: dict = Body(...)) -> JSONResponse:
        try:
            token, session = auth.login(str(body.get("password", "")), body.get("name"))
        except LoginError as err:
            return JSONResponse({"detail": str(err)}, status_code=401)
        response = JSONResponse(auth.describe(session))
        response.set_cookie(COOKIE, token, max_age=SESSION_S, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/")
        return response

    @app.post("/api/logout")
    def logout(request: Request) -> JSONResponse:
        auth.logout(request.cookies.get(COOKIE))
        response = JSONResponse(auth.describe(None))
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.post("/api/commands")
    def post_command(request: Request, body: dict = Body(...)) -> dict:
        """Send one operator command to the hub and return its reply: {"ok": ..., "result" or "error"}."""
        session = request.state.session
        command = {k: v for k, v in body.items() if k not in ("id", "by") and v is not None}
        if command.get("name") not in ACTIONS:
            raise HTTPException(422, f"name must be one of {', '.join(ACTIONS)}")
        command["by"] = f"dashboard:{session['name']}" if session else "dashboard"
        errors = [e.message for e in command_schema.iter_errors({**command, "id": "x"})]
        if errors:
            raise HTTPException(422, "; ".join(errors))
        reply = live.command(command)
        if reply is None:
            raise HTTPException(504, "the hub did not answer; is it running?")
        return reply

    def store() -> Store:
        try:
            return Store(db_path, readonly=True)
        except Exception as err:    # sqlite3.OperationalError: file missing or not yet created
            raise HTTPException(503, f"hub database is not readable yet: {err}") from None

    def quantities(device_id: str) -> list[dict]:
        dev = site.devices[device_id]
        return [m for role in dev.roles for m in components[role].get("measures", [])]

    def zone_or_404(zone_id: str):
        if zone_id not in site.zones:
            raise HTTPException(404, f"unknown zone {zone_id!r}")
        return site.zones[zone_id]

    def stage_of(planting_id: str | None, hub: dict | None) -> tuple[dict | None, dict | None]:
        """(planting state from the hub, the recipe stage it is in)"""
        state = (hub or {}).get("plantings", {}).get(planting_id) if planting_id else None
        if not state or state["stage"] is None:
            return state, None
        return state, site.plantings[planting_id].recipe["stages"][state["stage_index"]]

    def zone_view(zone_id: str, snap: dict, now: datetime) -> dict:
        zone = site.zones[zone_id]
        hub = snap["hub"]
        status = snap["zones"].get(zone_id)
        planting_id = next((pid for pid, p in (hub or {}).get("plantings", {}).items() if p["zone"] == zone_id), None)
        state, stage = stage_of(planting_id, hub)
        overrides = (hub or {}).get("overrides", {}).get(zone_id, {})
        targets = {}
        for quantity, band in (stage or {}).get("targets", {}).items():
            over = {k: v for k, v in overrides.get(quantity, {}).items() if k != "until"}
            targets[quantity] = {**band, **over, "overridden": bool(over)}
        readings = []
        for dev in site.zone_devices(zone_id, cls="sensor"):
            entry = snap["devices"].get(dev.id)
            for measure in quantities(dev.id):
                value = (entry or {}).get("state", {}).get(measure["quantity"])
                readings.append({"quantity": measure["quantity"], "unit": measure.get("unit"), "device": dev.id,
                                 "value": value if isinstance(value, (int, float)) else None,
                                 "age_s": _age(now, entry["received"]) if entry else None,
                                 "band": targets.get(measure["quantity"])})
        planting = None
        if state:
            started = datetime.fromisoformat(state["stage_started_at"])
            duration = (stage or {}).get("duration", {})
            typical = seconds(duration["typical"]) if "typical" in duration else None
            recipe = site.plantings[planting_id].recipe
            planting = {"id": planting_id, "species": site.plantings[planting_id].species.get("common_name"),
                        "recipe": state["recipe"], "stage": state["stage"], "stage_index": state["stage_index"],
                        "stages": [s["id"] for s in recipe["stages"]], "stage_started_at": state["stage_started_at"],
                        "day": int((now - started).total_seconds() // 86400) + 1,
                        "typical_days": round(typical / 86400, 1) if typical else None,
                        "due_in_s": round(typical - (now - started).total_seconds()) if typical else None,
                        "ready": state["ready"], "hint": (stage or {}).get("advance", {}).get("hint")}
        actions: dict = {"water": None, "advance": None}
        if state and stage:
            dose = next((lp for lp in stage["control"] if lp["strategy"] == "dose"), None)
            if dose:
                actions["water"] = {"loop": dose["id"], "volume_ml": dose["dose"]["volume_ml"]}
            stages = site.plantings[planting_id].recipe["stages"]
            if state["stage_index"] + 1 >= len(stages):
                actions["advance"] = {"planting": planting_id, "to_stage": None, "to_zone": None, "blocked": None}
            else:
                following = stages[state["stage_index"] + 1]
                role, target, blocked = following.get("zone_role"), zone_id, None
                if role and zone.role != role:      # the hub moves it to the first free zone with that role
                    taken = {p["zone"] for p in (hub or {}).get("plantings", {}).values() if p["zone"]}
                    free = [z.id for z in site.zones.values() if z.role == role and z.id not in taken]
                    target = free[0] if free else None
                    blocked = None if free else f"no free zone with role {role}"
                actions["advance"] = {"planting": planting_id, "to_stage": following["id"], "to_zone": target, "blocked": blocked}
        nodes = sorted({site.devices[d].node for d in zone.device_ids})
        ages = [r["age_s"] for r in readings if r["age_s"] is not None]
        raw_zone = next(z for z in site.raw["zones"] if z["id"] == zone_id)
        return {"id": zone_id, "name": raw_zone.get("name", zone_id), "kind": zone.kind, "role": zone.role,
                "status": status["state"] if status else "unknown",
                "active": status["active"] if status else [],
                "status_since": status["t"] if status else None,
                "planting": planting, "readings": readings,
                "nodes": [{"id": n, "online": snap["nodes"].get(n, {}).get("online")} for n in nodes],
                "last_reading_age_s": min(ages) if ages else None,
                "observing": (hub or {}).get("observing", {}).get(zone_id),
                "actions": actions,
                "paused": zone_id in (hub or {}).get("paused", {}),
                "paused_until": (hub or {}).get("paused", {}).get(zone_id),
                "overrides": overrides}

    # ------------------------------------------------------------------ site and current state

    @app.get("/api/health")
    def health() -> dict:
        snap = live.snapshot()
        return {"site": site.id, "hub_seen": snap["hub"] is not None, "now": live.now().isoformat()}

    @app.get("/api/site")
    def get_site() -> dict:
        theme = site.theme
        return {"id": site.id, "name": site.raw.get("name", site.id), "timezone": site.timezone,
                "theme": {"priority": theme["priority"], "statuses": theme["statuses"]},
                "zones": [{"id": z.id, "kind": z.kind, "role": z.role, "devices": z.device_ids, "indicator": z.indicator}
                          for z in site.zones.values()],
                "nodes": [{"id": n["id"], "board": n["board"], "runtime": n["runtime"]} for n in site.raw["nodes"]],
                "plantings": [{"id": p.id, "species": p.species.get("common_name"), "recipe": p.recipe["id"],
                               "layers": p.recipe["layers"],
                               "stages": [{"id": s["id"], "duration": s.get("duration"), "targets": s["targets"],
                                           "zone_role": s.get("zone_role")} for s in p.recipe["stages"]]}
                              for p in site.plantings.values()]}

    @app.get("/api/sim")
    def get_sim() -> dict:
        """The simulator's state, when this is a simulated site. `present` is false on real hardware."""
        state = live.snapshot()["sim"]
        return {"present": state is not None, "now": live.now().isoformat(), **(state or {})}

    @app.post("/api/sim")
    def post_sim(body: dict = Body(...)) -> dict:
        """Speed, pause and fault injection. Reaches only a simulator: real nodes do not listen on this topic."""
        if live.snapshot()["sim"] is None:
            raise HTTPException(409, "no simulator is running on this site")
        errors = [e.message for e in sim_schema.iter_errors(body)]
        if errors:
            raise HTTPException(422, "; ".join(errors))
        live.bus.publish(topics.sim_cmd(site.id), body)
        return {"sent": True}

    @app.get("/api/help")
    def get_help_index() -> dict:
        """Every status that has a guide, in the order the strip prioritises them, and the symptom guides."""
        doc = troubleshooting.load(catalog, site.theme["id"])
        return {"statuses": [{"status": s, "label": site.theme["statuses"][s].get("label", s),
                              "meaning": site.theme["statuses"][s].get("meaning", "")}
                             for s in site.theme["priority"] if s in doc["statuses"]],
                "symptoms": doc["symptoms"]}

    @app.get("/api/help/{status}")
    def get_help(status: str) -> dict:
        entry = troubleshooting.for_status(catalog, status, site.theme["id"])
        if entry is None:
            raise HTTPException(404, f"no troubleshooting guide for {status!r}")
        return entry

    @app.get("/api/zones")
    def get_zones() -> dict:
        snap, now = live.snapshot(), live.now()
        priority = site.theme["priority"]
        views = [zone_view(z, snap, now) for z in site.zones]
        # Problems first: by the theme's priority, which is what the LED strip uses too.
        views.sort(key=lambda v: priority.index(v["status"]) if v["status"] in priority else -1)
        return {"now": now.isoformat(), "hub": {k: (snap["hub"] or {}).get(k) for k in ("version", "started_at", "tick_ms", "t")},
                "zones": views}

    @app.get("/api/zones/{zone_id}")
    def get_zone(zone_id: str) -> dict:
        zone_or_404(zone_id)
        snap, now = live.snapshot(), live.now()
        view = zone_view(zone_id, snap, now)
        db = store()
        try:
            latest: dict[tuple[str, str], dict] = {}
            for d in db.decisions(zone=zone_id, since=now - timedelta(days=2)):
                latest[(d["loop"], d["device"])] = d
            view["decisions"] = [{**d, "t": d["t"].isoformat()} for d in latest.values()]
            stages = [e for kind in ("planting_started", "stage_advanced") for e in db.events(kind, zone=zone_id)]
            view["stage_history"] = sorted(({"t": e["t"].isoformat(), "planting": e["planting"],
                                             "stage": e.get("to_stage"), "by": e.get("by")} for e in stages),
                                           key=lambda e: e["t"])
        finally:
            db.close()
        actuators = (snap["hub"] or {}).get("actuators", {})
        view["actuators"] = [{"id": d.id, "roles": d.roles, **actuators.get(d.id, {})}
                             for d in site.zone_devices(zone_id, cls="actuator")]
        indicator = site.zones[zone_id].indicator
        strip = snap["devices"].get(indicator["strip"], {}).get("state", {}) if indicator else {}
        view["led"] = next((s for s in strip.get("segments", []) if s.get("zone") == zone_id), None)
        view["now"] = now.isoformat()
        return view

    # ------------------------------------------------------------------ history

    @app.get("/api/zones/{zone_id}/series")
    def get_series(zone_id: str, quantity: str, start: str | None = Query(None, alias="from"),
                   end: str | None = Query(None, alias="to"), resolution: str = "auto") -> dict:
        zone_or_404(zone_id)
        device = next((d for d in site.zone_devices(zone_id, cls="sensor")
                       if any(m["quantity"] == quantity for m in quantities(d.id))), None)
        if device is None:
            raise HTTPException(404, f"zone {zone_id} has no sensor for {quantity!r}")
        now = live.now()
        until = _parse(end, "to") or now
        since = _parse(start, "from") or until - timedelta(hours=24)
        if since >= until:
            raise HTTPException(422, "from must be before to")
        if resolution == "auto":
            span = (until - since).total_seconds()
            resolution = "raw" if span <= RAW_UP_TO else "5m" if span <= FIVE_MIN_UP_TO else "1h"
        if resolution not in RESOLUTIONS:
            raise HTTPException(422, f"resolution must be auto, {', '.join(RESOLUTIONS)}")
        res = RESOLUTIONS[resolution]
        db = store()
        try:
            if res == 0:
                rows = db.readings(device.id, quantity, since, until)
                t, mean, low, high = [r[0].timestamp() for r in rows], [r[1] for r in rows], None, None
            else:
                rolled = db.rollups(device.id, quantity, res, since, until)
                t = [r["t"].timestamp() for r in rolled]
                mean, low, high = [r["mean"] for r in rolled], [r["min"] for r in rolled], [r["max"] for r in rolled]
                # Rollups stop at the last whole hour: bucket the raw tail the same way.
                tail_from = max(since, db.rolled_up_until() or since)
                buckets: dict[int, list[float]] = {}
                for at, value in db.readings(device.id, quantity, tail_from, until):
                    buckets.setdefault(int(at.timestamp()) // res * res, []).append(value)
                for start_s, values in sorted(buckets.items()):
                    t.append(float(start_s))
                    mean.append(sum(values) / len(values))
                    low.append(min(values))
                    high.append(max(values))
        finally:
            db.close()
        if len(t) > MAX_POINTS:
            raise HTTPException(422, f"{len(t)} points: ask for a shorter range or a coarser resolution")
        unit = next(m.get("unit") for m in quantities(device.id) if m["quantity"] == quantity)
        return {"zone": zone_id, "quantity": quantity, "unit": unit, "device": device.id, "resolution": resolution,
                "from": since.isoformat(), "to": until.isoformat(), "t": t, "mean": mean, "min": low, "max": high}

    @app.get("/api/zones/{zone_id}/actuators")
    def get_actuator_history(zone_id: str, start: str | None = Query(None, alias="from"),
                             end: str | None = Query(None, alias="to")) -> dict:
        """On-intervals per actuator, rebuilt from the leased commands the hub sent."""
        zone_or_404(zone_id)
        now = live.now()
        until = _parse(end, "to") or now
        since = _parse(start, "from") or until - timedelta(hours=24)
        db = store()
        try:
            out = []
            for dev in site.zone_devices(zone_id, cls="actuator"):
                # Look back a little: an interval may have begun before the window.
                intervals = on_intervals(db.commands(device=dev.id, since=since - timedelta(hours=1)))
                lo, hi = since.timestamp(), min(until, now).timestamp()
                clipped = [[max(a, lo), min(b, hi)] for a, b in intervals if b > lo and a < hi]
                doses = [{"t": e["t"].timestamp(), "volume_ml": e["volume_ml"], "by": e.get("by")}
                         for e in db.events("dose", zone=zone_id, since=since) if e["device"] == dev.id and e["t"] < until]
                out.append({"id": dev.id, "roles": dev.roles, "intervals": clipped, "doses": doses,
                            "on_s": round(sum(b - a for a, b in clipped), 1)})
        finally:
            db.close()
        return {"zone": zone_id, "from": since.isoformat(), "to": until.isoformat(), "actuators": out}

    # ------------------------------------------------------------------ devices

    @app.get("/api/devices")
    def get_devices() -> dict:
        snap, now = live.snapshot(), live.now()
        actuators = (snap["hub"] or {}).get("actuators", {})
        tested: dict[str, dict] = {}
        for record in (snap["hub"] or {}).get("commissioning", []):
            if record["scope"] == "device":
                tested.setdefault(record["subject"], {})[record["step"]] = {k: record.get(k) for k in ("ok", "t", "by")}
        day_start = now - timedelta(hours=24)
        try:
            db = store()
        except HTTPException:
            db = None
        nodes = []
        try:
            for node in site.raw["nodes"]:
                devices = []
                for dev in (d for d in site.devices.values() if d.node == node["id"]):
                    entry = snap["devices"].get(dev.id)
                    state = (entry or {}).get("state", {})
                    driver = next((d for d in dev.model["drivers"] if d["runtime"] == node["runtime"]), None)
                    item = {"id": dev.id, "class": dev.cls, "roles": dev.roles, "model": dev.model["id"],
                            "model_name": dev.model.get("name"), "zones": site.zones_of_device(dev.id),
                            "driver_status": driver["status"] if driver else None, "pins": dev.raw.get("pins", {}),
                            "calibration": dev.raw.get("calibration"),
                            "datasheet_checked": dev.model.get("datasheet_checked"),
                            "commissioning": tested.get(dev.id, {}),
                            "age_s": _age(now, entry["received"]) if entry else None}
                    if dev.cls == "sensor":
                        item["values"] = [{"quantity": m["quantity"], "unit": m.get("unit"), "value": state.get(m["quantity"])}
                                          for m in quantities(dev.id)]
                    elif dev.cls == "actuator":
                        hub_view = actuators.get(dev.id, {})
                        lease = hub_view.get("lease_until") or hub_view.get("busy_until")
                        item.update(on=state.get("on"), level=state.get("level"), commanded_on=hub_view.get("on"),
                                    lease_remaining_s=max(0.0, -_age(now, lease)) if lease else None,
                                    locked_until=hub_view.get("locked_until"))
                        if db is not None:
                            sent = db.commands(device=dev.id, since=day_start)
                            runs = on_intervals(sent)
                            item["switched_on_24h"] = len(runs)
                            item["on_s_24h"] = round(sum(min(b, now.timestamp()) - a for a, b in runs), 1)
                            item["unacked"] = sum(1 for c in sent if c["ack_t"] is None)
                    devices.append(item)
                status = snap["nodes"].get(node["id"], {})
                nodes.append({"id": node["id"], "board": node["board"], "runtime": node["runtime"],
                              "online": status.get("online"), "since": status.get("since"), "devices": devices})
        finally:
            if db is not None:
                db.close()
        return {"now": now.isoformat(), "nodes": nodes}

    # ------------------------------------------------------------------ live updates

    @app.get("/api/stream")
    def stream(limit: int | None = None, raw: bool = False) -> StreamingResponse:
        return StreamingResponse(live.stream(limit=limit, raw=raw), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------ log and raw data

    def log_rows(db: Store, since: datetime | None, until: datetime | None) -> list[dict]:
        """Events and decision-trace rows as one list, oldest first."""
        rows = []
        for e in db.events(since=since, until=until, newest=LOG_SCAN):
            kind, device = e["kind"], e.get("device")
            zone = e["zone"] or next(iter(site.zones_of_device(device)), None) if device in site.devices else e["zone"]
            data = {k: v for k, v in e.items() if k not in ("t", "kind", "zone", "planting", "level", "id")}
            rows.append({"id": f"e{e['id']}", "t": e["t"].isoformat(), "source": "event", "level": e["level"], "kind": kind,
                         "group": GROUPS.get(kind, "other"), "zone": zone, "device": device, "node": e.get("node"),
                         "planting": e["planting"], "text": describe(kind, e), "data": data})
        for d in db.decisions(since=since, until=until, newest=LOG_SCAN):
            reason = d["reason"]
            level = "warn" if reason.startswith("fail-safe") else "info" if reason.startswith("blocked") else "debug"
            rows.append({"id": f"d{d['id']}", "t": d["t"].isoformat(), "source": "decision", "level": level, "kind": "decision",
                         "group": "decision", "zone": d["zone"], "device": d["device"], "node": None, "planting": None,
                         "text": f"{d['loop']}: {d['device']} {d['action']}, {reason}",
                         "data": {"loop": d["loop"], "want": d["want"], "action": d["action"], "reason": reason, "inputs": d["inputs"]}})
        rows.sort(key=lambda r: (r["t"], r["id"]))
        return rows

    @app.get("/api/log")
    def get_log(level: str = "debug", group: str | None = None, zone: str | None = None, device: str | None = None,
                planting: str | None = None, q: str | None = None, start: str | None = Query(None, alias="from"),
                end: str | None = Query(None, alias="to"), limit: int = Query(200, ge=1, le=LOG_SCAN),
                format: str = "json"):
        """The event log and the decision trace together, filtered. Newest `limit` matches, oldest first."""
        if level not in LEVELS:
            raise HTTPException(422, f"level must be one of {', '.join(LEVELS)}")
        if format not in ("json", "jsonl", "csv"):
            raise HTTPException(422, "format must be json, jsonl or csv")
        wanted = LEVELS[LEVELS.index(level):]
        groups = set(group.split(",")) if group else None
        needle = q.lower() if q else None
        db = store()
        try:
            rows = log_rows(db, _parse(start, "from"), _parse(end, "to"))
        finally:
            db.close()
        rows = [r for r in rows
                if r["level"] in wanted and (groups is None or r["group"] in groups)
                and (zone is None or r["zone"] == zone) and (device is None or r["device"] == device)
                and (planting is None or r["planting"] == planting)
                and (needle is None or needle in json.dumps(r).lower())][-limit:]
        if format != "json":
            return as_file(rows, ["t", "level", "kind", "zone", "device", "planting", "text", "data"], format, f"{site.id}-log")
        return {"now": live.now().isoformat(), "rows": rows, "groups": sorted(set(GROUPS.values()) | {"decision", "other"}),
                "levels": list(LEVELS)}

    @app.get("/api/mqtt/recent")
    def get_mqtt(topic: str | None = None, limit: int = Query(200, ge=1, le=2000)) -> dict:
        return {"now": live.now().isoformat(), "messages": live.recent(topic, limit)}

    @app.get("/api/readings")
    def get_readings(device: str, quantity: str, start: str | None = Query(None, alias="from"),
                     end: str | None = Query(None, alias="to"), format: str = "json"):
        """Raw samples of one device, never rolled up."""
        if device not in site.devices:
            raise HTTPException(404, f"unknown device {device!r}")
        if format not in ("json", "csv"):
            raise HTTPException(422, "format must be json or csv")
        until = _parse(end, "to") or live.now()
        since = _parse(start, "from") or until - timedelta(hours=6)
        db = store()
        try:
            samples = db.readings(device, quantity, since, until)
        finally:
            db.close()
        if len(samples) > MAX_POINTS and format == "json":
            raise HTTPException(422, f"{len(samples)} samples: ask for a shorter range or download the CSV")
        rows = [{"t": t.isoformat(), "value": value} for t, value in samples]
        if format == "csv":
            return as_file(rows, ["t", "value"], "csv", f"{site.id}-{device}-{quantity}")
        return {"device": device, "quantity": quantity, "from": since.isoformat(), "to": until.isoformat(), "samples": rows}

    @app.get("/api/export/diagnostics")
    def export_diagnostics() -> Response:
        """Everything needed to look at a problem from afar, with secrets replaced."""
        now = live.now()
        snap = live.snapshot()
        bundle = {"generated": now.isoformat(), "site": redact(site.raw), "hub": snap["hub"], "zones": snap["zones"],
                  "nodes": snap["nodes"], "devices": snap["devices"], "log": [], "database": None}
        try:
            db = store()
            try:
                bundle["log"] = log_rows(db, now - timedelta(hours=24), None)
                bundle["database"] = db.counts()
            finally:
                db.close()
        except HTTPException as err:
            bundle["database"] = str(err.detail)
        return Response(json.dumps(bundle, indent=1), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{site.id}-diagnostics.json"'})

    @app.get("/api/export/db")
    def export_db() -> FileResponse:
        if not developer:
            raise HTTPException(403, "database download is off; start the dashboard with --developer to allow it")
        db = store()
        handle, target = tempfile.mkstemp(suffix=".db")
        try:
            import os
            os.close(handle)
            os.unlink(target)
            db.snapshot(target)
        finally:
            db.close()
        return FileResponse(target, filename=f"{site.id}-hub.db", media_type="application/vnd.sqlite3",
                            background=BackgroundTask(lambda: Path(target).unlink(missing_ok=True)))

    @app.get("/api/meta")
    def meta() -> dict:
        return {"developer": developer, "raw_buffer": len(live.recent(limit=2000))}

    # ------------------------------------------------------------------ frontend

    if static_dir and (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            file = static_dir / path
            if path and file.is_file() and static_dir in file.resolve().parents:
                return FileResponse(file)
            return FileResponse(static_dir / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend() -> dict:
            return {"message": "The API is running; the frontend has not been built. Run `just web-build`.", "api": "/api/docs"}

    return app
