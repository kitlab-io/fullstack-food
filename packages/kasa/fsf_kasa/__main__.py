"""Run the bridge for one smart power strip.

    FSF_KASA_HOST=<address of the strip> python -m fsf_kasa --site sites/local/my-site --node plug-strip

The strip's address is read from the environment (or --host) and is never written to the
site file. With --dry-run no strip is contacted: outlets exist only in memory.
"""

from __future__ import annotations

import argparse
import os
import signal
import time
from pathlib import Path

from fsf_core import Catalog, MqttBus, SystemClock, find_repo_root, load_site, topics

from .bridge import MemoryBackend, PlugBridge


def main() -> None:
    parser = argparse.ArgumentParser(prog="fsf_kasa")
    parser.add_argument("--site", required=True, help="site directory or site.yaml")
    parser.add_argument("--node", required=True, help="the node in the site file that is this strip")
    parser.add_argument("--host", default=os.environ.get("FSF_KASA_HOST"), help="address of the strip")
    parser.add_argument("--mqtt-host", default=os.environ.get("FSF_MQTT_HOST", "localhost"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("FSF_MQTT_PORT", "1883")))
    parser.add_argument("--dry-run", action="store_true", help="switch nothing real")
    args = parser.parse_args()

    catalog = Catalog.load(find_repo_root(Path.cwd()))
    site = load_site(args.site, catalog)
    if args.dry_run:
        backend = MemoryBackend()
    else:
        if not args.host:
            parser.error("give the strip's address with --host or FSF_KASA_HOST")
        from .backend import KasaBackend
        backend = KasaBackend(args.host)
    bus = MqttBus(args.mqtt_host, args.mqtt_port, client_id=f"fsf-kasa-{site.id}-{args.node}",
                  username=os.environ.get("FSF_MQTT_USERNAME"), password=os.environ.get("FSF_MQTT_PASSWORD"),
                  will=(topics.node_status(site.id, args.node), "offline"))
    bridge = PlugBridge(site, args.node, bus, SystemClock(), backend)
    bridge.start()
    print(f"kasa: node {args.node} of site {site.id}, {len(bridge.devices)} outlet(s)"
          + (" (dry run)" if args.dry_run else ""), flush=True)

    running = True

    def halt(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, halt)
    try:
        while running:
            bus.poll()
            bridge.tick()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()       # everything off before we go
        bus.poll()
        bus.close()


if __name__ == "__main__":
    main()
