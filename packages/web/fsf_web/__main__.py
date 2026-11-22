"""Serve the dashboard for one site.

    python -m fsf_web --site sites/examples/houseplants --db hub.db --mqtt-host localhost

Binds to 127.0.0.1 unless told otherwise. There is no login yet (dashboard plan phase D4),
and nothing here can change the system: the API is read-only.
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from pathlib import Path

import uvicorn

from fsf_core import BusClock, Catalog, MqttBus, SystemClock, find_repo_root, load_site

from .app import create_app
from .live import Live


def main() -> None:
    parser = argparse.ArgumentParser(prog="fsf_web")
    parser.add_argument("--site", required=True, help="site directory or site.yaml")
    parser.add_argument("--db", default=os.environ.get("FSF_DB", "hub.db"), help="the hub's SQLite file (opened read-only)")
    parser.add_argument("--mqtt-host", default=os.environ.get("FSF_MQTT_HOST", "localhost"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("FSF_MQTT_PORT", "1883")))
    parser.add_argument("--clock", choices=["system", "bus"], default="system",
                        help="bus: follow the simulator's time, as the hub does in the mock stack")
    parser.add_argument("--host", default=os.environ.get("FSF_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("FSF_WEB_PORT", "8080")))
    parser.add_argument("--static", default=os.environ.get("FSF_WEB_STATIC"), help="folder with the built frontend")
    args = parser.parse_args()

    root = find_repo_root(Path.cwd())
    catalog = Catalog.load(root)
    site = load_site(args.site, catalog)
    bus = MqttBus(args.mqtt_host, args.mqtt_port, client_id=f"fsf-web-{site.id}",
                  username=os.environ.get("FSF_MQTT_USERNAME"), password=os.environ.get("FSF_MQTT_PASSWORD"))
    clock = BusClock(bus, site.id) if args.clock == "bus" else SystemClock()
    live = Live(site.id, bus, clock)

    def pump() -> None:     # MqttBus hands messages over only from poll()
        while True:
            bus.poll()
            time.sleep(0.05)

    threading.Thread(target=pump, name="mqtt-poll", daemon=True).start()
    while clock.now() is None:      # bus clock: wait for the simulator's first tick
        time.sleep(0.05)

    static = Path(args.static) if args.static else root / "packages" / "web" / "frontend" / "dist"
    app = create_app(site, catalog, args.db, live, static)
    print(f"web: site {site.id} on http://{args.host}:{args.port} (db {args.db}, clock {args.clock})", flush=True)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        bus.close()


if __name__ == "__main__":
    main()
