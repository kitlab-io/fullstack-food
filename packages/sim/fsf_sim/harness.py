"""MockSystem: a whole site (hub + simulated nodes) in one process on a virtual clock.

This is what the scenario tests drive. It is deterministic: the same site and seed
give the same run every time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from fsf_core import Catalog, InMemoryBus, VirtualClock, find_repo_root, load_site
from fsf_hub import Hub, Store

from .world import Sim

DEFAULT_START = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


class MockSystem:
    def __init__(self, site_dir: str | Path, db_path: str = ":memory:", start: datetime | None = None,
                 tick: float = 30.0, record_readings: bool = False, catalog: Catalog | None = None,
                 sim_config: dict | None = None):
        """sim_config: the simulated environment, instead of the site's sim.yaml."""
        root = find_repo_root()
        site_dir = Path(site_dir)
        if not site_dir.is_absolute():
            site_dir = root / site_dir
        self.catalog = catalog or Catalog.load(root)
        self.site = load_site(site_dir, self.catalog)
        sim_file = site_dir / "sim.yaml"
        if sim_config is None:
            sim_config = yaml.safe_load(sim_file.read_text(encoding="utf-8")) if sim_file.exists() else {}
        self.tick = tick
        self.db_path = db_path
        self.record_readings = record_readings
        self.clock = VirtualClock(start or DEFAULT_START)
        self.bus = InMemoryBus()
        self.sim = Sim(self.site, sim_config, self.bus, self.clock)
        self.sim.start()
        self.hub: Hub | None = None
        self.start_hub()

    # -- hub lifecycle (the simulated nodes keep running while the hub is down)
    def start_hub(self) -> None:
        self.hub = Hub(self.site, self.catalog, self.bus, self.clock, Store(self.db_path),
                       record_readings=self.record_readings)
        self.hub.start()
        self.hub.tick()

    def stop_hub(self) -> None:
        self.hub.stop()
        self.hub.store.close()
        self.hub = None

    # -- time
    def run(self, seconds: float = 0, *, minutes: float = 0, hours: float = 0, days: float = 0,
            until: Callable[[], bool] | None = None, each_tick: Callable[[], None] | None = None) -> bool:
        """Advance simulated time. With `until`, stop early and return True once it holds."""
        total = seconds + minutes * 60 + hours * 3600 + days * 86400
        for _ in range(int(round(total / self.tick))):
            self.clock.advance(self.tick)
            self.sim.step(self.tick)
            if self.hub:
                self.hub.tick()
            if each_tick:
                each_tick()
            if until and until():
                return True
        return False

    # -- inspection helpers
    def status(self, zone_id: str) -> str:
        return self.hub.zone_status[zone_id]["state"]

    def active(self, zone_id: str) -> list[str]:
        return self.hub.zone_status[zone_id]["active"]

    def led(self, zone_id: str) -> dict | None:
        """What the zone's LED segment is currently showing, as the node received it."""
        indicator = self.site.zones[zone_id].indicator
        render = self.sim.leds.get(indicator["strip"]) if indicator else None
        if not render:
            return None
        return next(s for s in render["segments"] if s["zone"] == zone_id)

    def led_statuses(self, zone_id: str) -> list[str]:
        """Every status the zone's segment has shown, in order, without repeats."""
        strip = self.site.zones[zone_id].indicator["strip"]
        out: list[str] = []
        for _, by_zone in self.sim.led_history.get(strip, []):
            if not out or out[-1] != by_zone[zone_id]:
                out.append(by_zone[zone_id])
        return out

    def events(self, kind: str, zone: str | None = None) -> list[dict]:
        return self.hub.store.events(kind, zone=zone)

    def is_on(self, device_id: str) -> bool:
        return self.sim.actuators[device_id].is_on(self.clock.now())
