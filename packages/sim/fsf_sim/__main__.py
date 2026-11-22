"""Run the simulated nodes of a site against an MQTT broker.

    python -m fsf_sim --site sites/examples/mushrooms --mqtt-host localhost --speed 120

The simulator owns simulated time and publishes it on the clock topic; start the hub
with --clock bus so it follows along.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import yaml

from fsf_core import Catalog, MqttBus, VirtualClock, find_repo_root, load_site

from .harness import DEFAULT_START
from .world import Sim


def main() -> None:
    parser = argparse.ArgumentParser(prog="fsf_sim")
    parser.add_argument("--site", required=True, help="site directory containing site.yaml and sim.yaml")
    parser.add_argument("--mqtt-host", default=os.environ.get("FSF_MQTT_HOST", "localhost"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("FSF_MQTT_PORT", "1883")))
    parser.add_argument("--speed", type=float, default=float(os.environ.get("FSF_SPEED", "1")),
                        help="simulated seconds per real second")
    parser.add_argument("--tick", type=float, default=30.0, help="simulated seconds per physics step")
    args = parser.parse_args()

    site_dir = Path(args.site)
    catalog = Catalog.load(find_repo_root(Path.cwd()))
    site = load_site(site_dir, catalog)
    sim_file = (site_dir if site_dir.is_dir() else site_dir.parent) / "sim.yaml"
    config = yaml.safe_load(sim_file.read_text(encoding="utf-8")) if sim_file.exists() else {}

    bus = MqttBus(args.mqtt_host, args.mqtt_port, client_id=f"fsf-sim-{site.id}")
    clock = VirtualClock(DEFAULT_START)
    sim = Sim(site, config, bus, clock)
    sim.start()
    print(f"sim: {len(site.nodes)} node(s) for site {site.id} at {args.speed:g}x "
          f"against {args.mqtt_host}:{args.mqtt_port}", flush=True)
    try:
        while True:
            started = time.monotonic()
            bus.poll()
            clock.advance(args.tick)
            sim.step(args.tick)
            # Keep polling while we wait so hub commands land promptly.
            deadline = started + args.tick / args.speed
            while time.monotonic() < deadline:
                bus.poll()
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        bus.close()


if __name__ == "__main__":
    main()
