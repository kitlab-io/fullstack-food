"""Serve the dashboard for one site.

    python -m fsf_web --site sites/examples/houseplants --db hub.db --mqtt-host localhost
    python -m fsf_web hash-password        # make the value for FSF_WEB_PASSWORD_HASH

Binds to 127.0.0.1 unless told otherwise. Everything needs the shared login unless
--read-without-login (pages open, actions need the login) or --no-login (no authentication
at all: only for a port published on this machine, as in the mock stack).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import threading
import time
from pathlib import Path

import uvicorn

from fsf_core import BusClock, Catalog, MqttBus, SystemClock, find_repo_root, load_site

from .app import create_app
from .auth import Auth, hash_password
from .live import Live


def main() -> None:
    if sys.argv[1:2] == ["hash-password"]:
        first = getpass.getpass("Dashboard password: ")
        if len(first) < 8 or first != getpass.getpass("Again: "):
            sys.exit("passwords differ or are shorter than 8 characters")
        print(hash_password(first))
        return
    parser = argparse.ArgumentParser(prog="fsf_web")
    parser.add_argument("--site", required=True, help="site directory or site.yaml")
    parser.add_argument("--db", default=os.environ.get("FSF_DB", "hub.db"), help="the hub's SQLite file (opened read-only)")
    parser.add_argument("--mqtt-host", default=os.environ.get("FSF_MQTT_HOST", "localhost"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("FSF_MQTT_PORT", "1883")))
    parser.add_argument("--clock", choices=["system", "bus"], default="system",
                        help="bus: follow the simulator's time, as the hub does in the mock stack")
    parser.add_argument("--host", default=os.environ.get("FSF_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("FSF_WEB_PORT", "8080")))
    parser.add_argument("--developer", action="store_true", help="allow downloading the whole database")
    parser.add_argument("--read-without-login", action="store_true",
                        default=os.environ.get("FSF_WEB_READ_WITHOUT_LOGIN") == "1", help="anyone who can reach the service may read")
    parser.add_argument("--no-login", action="store_true", default=os.environ.get("FSF_WEB_NO_LOGIN") == "1",
                        help="no authentication at all; only with the port published on this machine")
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
    password_hash = os.environ.get("FSF_WEB_PASSWORD_HASH") or None
    auth = Auth(password_hash, read_without_login=args.read_without_login, no_login=args.no_login,
                viewer_hash=os.environ.get("FSF_WEB_VIEWER_PASSWORD_HASH") or None,
                admin_hash=os.environ.get("FSF_WEB_ADMIN_PASSWORD_HASH") or None)
    site_dir = Path(args.site) if Path(args.site).is_dir() else Path(args.site).parent
    app = create_app(site, catalog, args.db, live, static, developer=args.developer, auth=auth, site_dir=site_dir)
    access = ("NO LOGIN: anyone who can reach this port can act" if args.no_login
              else "no password configured: nobody can log in" if not auth.hashes
              else f"login required ({', '.join(auth.hashes)})"
              + (" to act, reading is open" if args.read_without_login else ""))
    print(f"web: site {site.id} on http://{args.host}:{args.port} (db {args.db}, clock {args.clock}); {access}", flush=True)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        bus.close()


if __name__ == "__main__":
    main()
