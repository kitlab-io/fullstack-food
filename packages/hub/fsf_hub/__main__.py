"""Run the hub against an MQTT broker.

    python -m fsf_hub --site sites/examples/houseplants --mqtt-host localhost

With --clock bus the hub follows the time published by a simulator, so it can run
against an accelerated mock system.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from fsf_core import BusClock, Catalog, MqttBus, SystemClock, find_repo_root, load_site

from .hub import Hub
from .store import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="fsf_hub")
    parser.add_argument("--site", required=True, help="site directory or site.yaml")
    parser.add_argument("--mqtt-host", default=os.environ.get("FSF_MQTT_HOST", "localhost"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("FSF_MQTT_PORT", "1883")))
    parser.add_argument("--db", default=os.environ.get("FSF_DB", ":memory:"), help="SQLite file for readings and events")
    parser.add_argument("--reset-db", action="store_true",
                        help="delete the database file first (mock runs: simulated time restarts with every run)")
    parser.add_argument("--tick", type=float, default=30.0, help="seconds of (possibly simulated) time between control ticks")
    parser.add_argument("--clock", choices=["system", "bus"], default="system")
    args = parser.parse_args()

    catalog = Catalog.load(find_repo_root(Path.cwd()))
    site = load_site(args.site, catalog)
    bus = MqttBus(args.mqtt_host, args.mqtt_port, client_id=f"fsf-hub-{site.id}",
                  username=os.environ.get("FSF_MQTT_USERNAME"), password=os.environ.get("FSF_MQTT_PASSWORD"))
    clock = BusClock(bus, site.id) if args.clock == "bus" else SystemClock()

    while clock.now() is None:      # bus clock: wait for the simulator's first tick
        bus.poll()
        time.sleep(0.05)
    if args.reset_db and args.db != ":memory:":
        for suffix in ("", "-wal", "-shm"):
            Path(args.db + suffix).unlink(missing_ok=True)
    hub = Hub(site, catalog, bus, clock, Store(args.db))
    hub.start()
    print(f"hub: running site {site.id} against {args.mqtt_host}:{args.mqtt_port} (clock: {args.clock})", flush=True)

    last_tick = None
    last_state: dict[str, str] = {}
    try:
        while True:
            bus.poll()
            now = clock.now()
            if last_tick is None or (now - last_tick).total_seconds() >= args.tick:
                hub.tick()
                hub.store.commit()
                last_tick = now
                for zone_id, status in hub.zone_status.items():
                    if last_state.get(zone_id) != status["state"]:
                        print(f"hub: {now:%Y-%m-%d %H:%M} zone {zone_id}: {status['state']} "
                              f"(stage {status['stage']}, {status['readings']})", flush=True)
                        last_state[zone_id] = status["state"]
            time.sleep(0.02 if args.clock == "bus" else 0.5)
    except KeyboardInterrupt:
        pass
    finally:
        hub.stop()
        bus.close()


if __name__ == "__main__":
    main()
