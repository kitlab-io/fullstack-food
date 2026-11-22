"""The dashboard's HTTP API (read-only) and static frontend.

Reads come from the hub's SQLite file, opened read-only for each request, and from what
MQTT says is true right now (live.py). The service never writes to the database and never
publishes to device topics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from fsf_core import Catalog, Site, seconds
from fsf_hub import Store

from .live import Live

RAW_UP_TO = 12 * 3600           # spans up to this long are served as raw samples
FIVE_MIN_UP_TO = 4 * 86400      # then 5-minute rollups, then hourly
RESOLUTIONS = {"raw": 0, "5m": 300, "1h": 3600}
MAX_POINTS = 20000


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


def create_app(site: Site, catalog: Catalog, db_path: str, live: Live, static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Fullstack Food", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    components = catalog.items["Component"]

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
    def stream(limit: int | None = None) -> StreamingResponse:
        return StreamingResponse(live.stream(limit=limit), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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
