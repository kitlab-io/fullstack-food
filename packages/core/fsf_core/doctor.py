"""`fsf doctor`: a pass/fail health check of a running installation, with the fix for each failure.

    fsf doctor --site sites/local/my-site --mqtt-host localhost --db /data/hub.db
    fsf doctor ... --bundle diagnostics.zip      # also write an archive to attach to an issue

It only listens on the bus and reads files; it changes nothing.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import topics
from .catalog import Catalog, Site
from .nodetest import Check

SECRET_KEY = re.compile(r"pass|secret|token|key|credential", re.IGNORECASE)
BAD_STATUSES = {"offline", "sensor_stale", "sensor_fault", "actuator_fault", "no_effect", "water_mismatch",
                "node_unstable", "critical", "reservoir_low"}
MIN_FREE_MB = 500


def redact(node):
    """A copy with the value of anything that looks like a secret replaced."""
    if isinstance(node, dict):
        return {k: "<redacted>" if SECRET_KEY.search(str(k)) and not isinstance(v, (dict, list)) else redact(v)
                for k, v in node.items()}
    if isinstance(node, list):
        return [redact(item) for item in node]
    return node


class Doctor:
    """wait(seconds) must let time pass and deliver bus messages."""

    def __init__(self, site: Site, catalog: Catalog, bus, wait: Callable[[float], None], db_path: str | None = None,
                 listen_s: float = 3.0):
        self.site, self.catalog, self.bus, self.wait, self.db_path, self.listen_s = site, catalog, bus, wait, db_path, listen_s
        self.hub: dict | None = None
        self.zones: dict[str, dict] = {}
        self.nodes: dict[str, str] = {}
        self.devices: dict[str, dict] = {}
        self.sim_time: datetime | None = None
        bus.subscribe(f"{topics.ROOT}/{site.id}/#", self._on_message)

    def _on_message(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")[2:]
        text = payload.decode(errors="replace")
        try:
            if parts == ["hub", "state"]:
                self.hub = json.loads(text)
            elif parts == ["sim", "clock"]:
                self.sim_time = datetime.fromisoformat(json.loads(text)["t"])
            elif parts[0] == "zone" and parts[-1] == "status":
                self.zones[parts[1]] = json.loads(text)
            elif len(parts) == 2 and parts[1] == "status":
                self.nodes[parts[0]] = text
            elif len(parts) == 3 and parts[2] == "state":
                self.devices[parts[1]] = json.loads(text)
        except (ValueError, KeyError):
            pass                                        # the MQTT tail on the dashboard shows malformed payloads

    def now(self) -> datetime:
        return self.sim_time or datetime.now(timezone.utc)

    def _age(self, payload: dict) -> float | None:
        try:
            return (self.now() - datetime.fromisoformat(payload["t"])).total_seconds()
        except (KeyError, ValueError, TypeError):
            return None

    def run(self) -> list[Check]:
        self.wait(self.listen_s)
        checks = [self._hub()]
        checks += self._nodes()
        checks += self._sensors()
        checks += self._zones()
        checks += self._storage()
        checks += [self._clock(), self._docker(),
                   Check("backups", True, "not checked: there is no backup command yet; copy the database file yourself")]
        return checks

    def _hub(self) -> Check:
        if self.hub is None:
            return Check("hub is publishing its state", False,
                         "nothing on hub/state. Fix: check the broker address and that the hub is running (docker compose ps, hub log)")
        age = self._age(self.hub)
        fresh = age is not None and age < 900
        detail = (f"version {self.hub.get('version')}, last tick took {self.hub.get('tick_ms')} ms"
                  if fresh else f"last state is {age:.0f} s old. Fix: the hub has stopped; look at its log and restart it")
        return Check("hub is publishing its state", fresh, detail)

    def _nodes(self) -> list[Check]:
        out = []
        for node in self.site.nodes:
            status = self.nodes.get(node)
            fix = ("" if status == "online" else
                   " Fix: check its power and WiFi; if it never appeared, check the broker address and credentials in its firmware")
            out.append(Check(f"node {node} is online", status == "online", f"status is {status!r}.{fix}" if fix else ""))
        return out

    def _sensors(self) -> list[Check]:
        from fsf_hub.detect import plausible

        components = self.catalog.items["Component"]
        stale_after = self.site.safety["sensor_stale_after"]
        out = []
        for dev in self.site.devices.values():
            if dev.cls != "sensor" or not self.site.zones_of_device(dev.id):
                continue
            state = self.devices.get(dev.id)
            name = f"sensor {dev.id} reports plausible values"
            if state is None:
                out.append(Check(name, False, f"never heard. Fix: check its wiring, then fsf bench {dev.id}"))
                continue
            age = self._age(state)
            wanted = [m["quantity"] for role in dev.roles for m in components[role].get("measures", [])]
            missing = [q for q in wanted if not isinstance(state.get(q), (int, float))]
            wrong = [f"{q} = {state[q]:g}" for q in wanted if q not in missing and not plausible(q, state[q])]
            if age is not None and age > stale_after:
                out.append(Check(name, False, f"last reading is {age / 60:.0f} min old. Fix: reseat the connector, then fsf bench {dev.id}"))
            elif missing or wrong:
                what = ", ".join([f"no {q}" for q in missing] + wrong)
                out.append(Check(name, False, f"{what}. Fix: the probe is probably disconnected; check it, then fsf bench {dev.id}"))
            else:
                shown = ", ".join(f"{q} {state[q]:g}" for q in wanted)
                out.append(Check(name, True, shown + ("" if age is not None else " (no timestamp from the node)")))
        return out

    def _zones(self) -> list[Check]:
        out = []
        for zone in self.site.zones:
            status = self.zones.get(zone)
            if status is None:
                out.append(Check(f"zone {zone} has a status", False, "the hub has published none. Fix: see the hub check above"))
                continue
            bad = sorted(set(status["active"]) & BAD_STATUSES)
            detail = (f"{status['state']}" + (f"; needs attention: {', '.join(bad)}. Fix: fsf docs troubleshooting, or the "
                                              "dashboard's help page for each status" if bad else ""))
            out.append(Check(f"zone {zone} is healthy", not bad, detail))
        return out

    def _storage(self) -> list[Check]:
        if not self.db_path:
            return [Check("database", True, "not checked: pass --db with the hub's database file")]
        path = Path(self.db_path)
        if not path.exists():
            return [Check("database file exists", False, f"{path} not found. Fix: pass the path the hub was started with (--db)")]
        from fsf_hub import Store

        free_mb = shutil.disk_usage(path.parent).free / 1e6
        store = Store(str(path), readonly=True)
        try:
            counts = store.counts()
            oldest = store.events(newest=None)[:1]
        finally:
            store.close()
        size_mb = path.stat().st_size / 1e6
        since = f", events since {oldest[0]['t']:%Y-%m-%d}" if oldest else ""
        return [Check("database is readable", True, f"{size_mb:.1f} MB, {counts['readings']} raw readings, {counts['events']} events{since}"),
                Check("disk has room", free_mb >= MIN_FREE_MB,
                      f"{free_mb:.0f} MB free" + ("" if free_mb >= MIN_FREE_MB else
                                                  ". Fix: free space or shorten retention in the site file (retention: raw_readings)"))]

    def _clock(self) -> Check:
        now = datetime.now(timezone.utc)
        if now.year < 2025:
            return Check("system clock is set", False, f"it says {now:%Y-%m-%d}. Fix: enable time synchronisation on the hub host")
        if shutil.which("timedatectl"):
            try:
                out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True, text=True, timeout=5)
                if out.stdout.strip() == "no":
                    return Check("system clock is synchronised", False, "NTP is not synchronised. Fix: timedatectl set-ntp true")
                return Check("system clock is synchronised", True, "")
            except (OSError, subprocess.SubprocessError):
                pass
        return Check("system clock is set", True, f"{now:%Y-%m-%d %H:%M} UTC (synchronisation not checked on this system)")

    def _docker(self) -> Check:
        if shutil.which("docker") is None:
            return Check("docker", True, "not installed, which is fine when the hub runs without it")
        try:
            out = subprocess.run(["docker", "compose", "version", "--short"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as err:
            return Check("docker compose works", False, f"{err}. Fix: install the Docker Compose plugin")
        return Check("docker compose works", out.returncode == 0,
                     out.stdout.strip() or "docker compose is not available. Fix: install the Docker Compose plugin")

    def bundle(self, checks: list[Check], target: Path) -> Path:
        """A zip with the redacted site file, live state, the check results and the last day of events."""
        files = {
            "site.json": redact(self.site.raw),
            "checks.json": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
            "live.json": {"hub": self.hub, "zones": self.zones, "nodes": self.nodes, "devices": self.devices},
        }
        if self.db_path and Path(self.db_path).exists():
            from fsf_hub import Store

            store = Store(self.db_path, readonly=True)
            try:
                events = store.events(since=self.now() - timedelta(hours=24))
                files["events.json"] = [{**e, "t": e["t"].isoformat()} for e in events]
            finally:
                store.close()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, json.dumps(redact(content) if name != "checks.json" else content, indent=1))
        target.write_bytes(buffer.getvalue())
        return target
