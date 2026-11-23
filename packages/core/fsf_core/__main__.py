"""The `fsf` command line (also `python -m fsf_core`).

    fsf validate [--pins] [site ...]        check the catalog and site files
    fsf firmware build <site>               one ESPHome config per node
    fsf firmware flash <site> <node>        compile and upload with the ESPHome command line
    fsf node test <node> --site <site>      run the node contract suite against a broker
    fsf docs build <site>                   BOM, wiring diagrams, build guide, checklist, LED legend
    fsf bench <device> --site <site>        bench-test one device and record the result
    fsf calibrate <device> --site <site>    measure a device's calibration values
    fsf zone mode <zone> observe|active     compute-only or really switching
    fsf zone test <zone> --site <site>      shortened acceptance run of a zone in observe mode
    fsf commissioning --site <site>         what has been tested so far
    fsf doctor --site <site>                health check of a running installation
    fsf docs troubleshooting                troubleshooting pages by status, symptom and part
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .catalog import Catalog, ConfigError, find_repo_root, load_site


def _validate(args, root: Path, catalog: Catalog) -> int:
    from .troubleshooting import load as load_troubleshooting

    try:
        guides = load_troubleshooting(catalog)
    except ConfigError as err:
        print("catalog: INVALID")
        print("\n".join(f"  {p}" for p in err.problems))
        return 1
    counts = ", ".join(f"{len(v)} {k.lower()}" for k, v in catalog.items.items())
    print(f"catalog: ok ({counts}, {len(guides['statuses'])} status guides)")
    sites = [Path(s) for s in args.sites] or sorted((root / "sites" / "examples").glob("*/site.yaml"))
    failed = False
    for path in sites:
        try:
            site = load_site(path, catalog)
            print(f"site {site.id}: ok ({len(site.devices)} devices, {len(site.zones)} zones, {len(site.plantings)} plantings)")
            for warning in site.warnings:
                print(f"  warning: {warning}")
            if args.pins:
                for device_id, pins in site.pin_proposals.items():
                    print(f"  propose: {device_id}: pins: {{ {', '.join(f'{s}: {p}' for s, p in pins.items())} }}")
                for line in site.pin_unassigned:
                    print(f"  no pin: {line}")
        except ConfigError as err:
            failed = True
            print(f"site {path}: INVALID")
            print("\n".join(f"  {p}" for p in err.problems))
    return 1 if failed else 0


def _firmware(args, root: Path, catalog: Catalog) -> int:
    from .firmware import FirmwareError, build, flash

    site = load_site(args.site, catalog)
    out_dir = Path(args.out) if args.out else root / "build" / "firmware" / site.id
    try:
        if args.action == "build":
            written, warnings = build(site, catalog, out_dir, str(args.site).replace("\\", "/"), include_sim=args.include_sim)
            for path in written:
                print(f"wrote {path}")
            for warning in warnings:
                print(f"warning: {warning}")
            print(f"next: copy {out_dir / 'secrets.example.yaml'} to secrets.yaml, fill it in, then `fsf firmware flash`")
            return 0
        return flash(out_dir / f"{args.node}.yaml", args.device)
    except FirmwareError as err:
        print("firmware: FAILED")
        print("\n".join(f"  {p}" for p in err.problems))
        return 1


def _docs(args, root: Path, catalog: Catalog) -> int:
    from .builddocs import build, power_budget

    if args.action == "troubleshooting":
        from .troubleshooting import build as build_troubleshooting

        for path in build_troubleshooting(catalog, Path(args.out) if args.out else root / "build" / "docs" / "troubleshooting"):
            print(f"wrote {path}")
        return 0
    site = load_site(args.site, catalog)
    out_dir = Path(args.out) if args.out else root / "build" / "docs" / site.id
    for path in build(site, catalog, out_dir):
        print(f"wrote {path}")
    for entry in power_budget(site, catalog):
        for warning in entry["warnings"]:
            print(f"warning: node {entry['node']}: {warning}")
    return 0


def _node_test(args, root: Path, catalog: Catalog) -> int:
    from .bus import MqttBus
    from .nodetest import NodeContract

    site = load_site(args.site, catalog)
    bus = MqttBus(args.mqtt_host, args.mqtt_port, client_id=f"fsf-nodetest-{site.id}",
                  username=os.environ.get("FSF_MQTT_USERNAME"), password=os.environ.get("FSF_MQTT_PASSWORD"))

    def wait(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            bus.poll()
            time.sleep(0.05)
        bus.poll()

    try:
        contract = NodeContract(site, catalog, args.node, bus, wait)
        if args.actuate:
            print(f"switching every actuator on {args.node} on for a few seconds", flush=True)

        def unplug() -> None:
            print(f"unplug {args.node} now; waiting up to 60 s for the broker to report it offline", flush=True)

        checks = contract.run(actuate=args.actuate, power_cut=unplug if args.last_will else None)
    except ValueError as err:
        print(f"node test: {err}")
        return 1
    finally:
        bus.close()
    for check in checks:
        print(check)
    failed = sum(not c.ok for c in checks)
    print(f"{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


def _doctor(args, root: Path, catalog: Catalog) -> int:
    from .bus import MqttBus
    from .doctor import Doctor

    site = load_site(args.site, catalog)
    print(f"site {site.id}: valid")
    try:
        bus = MqttBus(args.mqtt_host, args.mqtt_port, client_id=f"fsf-doctor-{site.id}",
                      username=os.environ.get("FSF_MQTT_USERNAME"), password=os.environ.get("FSF_MQTT_PASSWORD"))
    except OSError as err:
        print(f"FAIL  broker is reachable: {err}. Fix: check --mqtt-host and that the broker is running")
        return 1

    def wait(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            bus.poll()
            time.sleep(0.05)

    try:
        doctor = Doctor(site, catalog, bus, wait, db_path=args.db)
        checks = doctor.run()
        if args.bundle:
            print(f"wrote {doctor.bundle(checks, Path(args.bundle))} (secrets replaced)")
    finally:
        bus.close()
    for check in checks:
        print(check)
    failed = sum(not c.ok for c in checks)
    print(f"{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


class _Console:
    """Talks to the person doing the commissioning."""

    def say(self, text: str) -> None:
        print(f"\n>> {text}", flush=True)

    def confirm(self, question: str) -> bool:
        return input(f"   {question}? [y/N] ").strip().lower() in ("y", "yes")

    def number(self, question: str) -> float:
        while True:
            try:
                return float(input(f"   {question}: ").strip())
            except ValueError:
                print("   a number, please")


def _commissioning(args, root: Path, catalog: Catalog) -> int:
    from fsf_hub.commissioning import Bench, Calibrate, CommissioningError, HubClient, ZoneAcceptance

    from .bus import MqttBus
    from .clock import SystemClock

    site = load_site(args.site, catalog)
    bus = MqttBus(args.mqtt_host, args.mqtt_port, client_id=f"fsf-commission-{site.id}",
                  username=os.environ.get("FSF_MQTT_USERNAME"), password=os.environ.get("FSF_MQTT_PASSWORD"))

    def wait(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            bus.poll()
            time.sleep(0.05)
        bus.poll()

    try:
        hub = HubClient(site.id, bus, wait, by=os.environ.get("USER") or os.environ.get("USERNAME") or "fsf")
        if args.command == "commissioning":
            hub.observing(next(iter(site.zones)))        # waits for the retained hub state
            for zone_id, why in sorted(hub.state["observing"].items()):
                print(f"zone {zone_id}: observe ({why})")
            for record in sorted(hub.state["commissioning"], key=lambda r: (r["scope"], r["subject"], r["step"])):
                print(f"{record['scope']} {record['subject']}: {record['step']} {'passed' if record['ok'] else 'FAILED'} "
                      f"{record['t'][:16]} by {record.get('by') or 'unknown'}")
            return 0
        if args.command == "zone" and args.action == "mode":
            print(f"zone {args.zone}: {hub.call('set_zone_mode', zone=args.zone, mode=args.mode)['mode']}")
            return 0
        if args.command == "bench":
            checks = Bench(site, catalog, args.device, bus, wait, _Console(), hub).run()
        elif args.command == "calibrate":
            checks, values = Calibrate(site, catalog, args.device, bus, wait, _Console(), hub).run()
            if values:
                shown = ", ".join(f"{k}: {v}" for k, v in values.items())
                target = "the device" if "flow_ml_per_s" in values else "calibration: { ... } of the device"
                print(f"\nput into {target} in the site file, then rebuild and reflash the node:\n  {shown}")
        else:
            print(f"running zone {args.zone} for {args.minutes:g} min at {args.speed:g}x; its actuators will switch", flush=True)
            checks = ZoneAcceptance(site, catalog, args.zone, bus, SystemClock(), wait, hub, stage=args.stage,
                                    speed=args.speed, run_s=args.minutes * 60).run()
    except CommissioningError as err:
        print(f"{args.command}: {err}")
        return 1
    finally:
        bus.close()
    for check in checks:
        print(check)
    failed = sum(not c.ok for c in checks)
    print(f"{len(checks) - failed} passed, {failed} failed; recorded by the hub")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fsf")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate the catalog and site files")
    validate.add_argument("sites", nargs="*", help="site directories or files (default: sites/examples/*)")
    validate.add_argument("--pins", action="store_true", help="also propose pins for devices that have none assigned")

    firmware = sub.add_parser("firmware", help="generate and flash node firmware").add_subparsers(dest="action", required=True)
    build = firmware.add_parser("build", help="write one ESPHome config per node")
    build.add_argument("site", help="site directory or site.yaml")
    build.add_argument("--out", help="output folder (default: build/firmware/<site id>)")
    build.add_argument("--include-sim", action="store_true",
                       help="also build simulated nodes whose board can run ESPHome")
    flash = firmware.add_parser("flash", help="compile and upload one node with the esphome command")
    flash.add_argument("site", help="site directory or site.yaml")
    flash.add_argument("node")
    flash.add_argument("--out", help="folder the configs were built into")
    flash.add_argument("--device", help="serial port or address; default lets esphome choose")

    docs = sub.add_parser("docs", help="generate build documents").add_subparsers(dest="action", required=True)
    docs_build = docs.add_parser("build", help="BOM, wiring diagrams, build guide, checklist and LED legend for a site")
    docs_build.add_argument("site", help="site directory or site.yaml")
    docs_build.add_argument("--out", help="output folder (default: build/docs/<site id>)")

    docs_trouble = docs.add_parser("troubleshooting", help="troubleshooting pages by status, symptom and part")
    docs_trouble.add_argument("--out", help="output folder (default: build/docs/troubleshooting)")

    node = sub.add_parser("node", help="work with one node").add_subparsers(dest="action", required=True)
    test = node.add_parser("test", help="run the node contract suite against a broker")
    test.add_argument("node")
    test.add_argument("--site", required=True, help="site directory or site.yaml")
    test.add_argument("--mqtt-host", default=os.environ.get("FSF_MQTT_HOST", "localhost"))
    test.add_argument("--mqtt-port", type=int, default=int(os.environ.get("FSF_MQTT_PORT", "1883")))
    test.add_argument("--actuate", action="store_true", help="also switch every actuator on the node for a few seconds")
    test.add_argument("--last-will", action="store_true", help="ask for the node to be unplugged and check it is reported offline")

    def broker(p) -> None:
        p.add_argument("--site", required=True, help="site directory or site.yaml")
        p.add_argument("--mqtt-host", default=os.environ.get("FSF_MQTT_HOST", "localhost"))
        p.add_argument("--mqtt-port", type=int, default=int(os.environ.get("FSF_MQTT_PORT", "1883")))

    bench = sub.add_parser("bench", help="bench-test one device through the running hub")
    bench.add_argument("device")
    broker(bench)
    calibrate = sub.add_parser("calibrate", help="measure the calibration values of one device")
    calibrate.add_argument("device")
    broker(calibrate)
    zone = sub.add_parser("zone", help="zone mode and acceptance").add_subparsers(dest="action", required=True)
    mode = zone.add_parser("mode", help="observe: decisions are logged, nothing is switched")
    mode.add_argument("zone")
    mode.add_argument("mode", choices=["observe", "active"])
    broker(mode)
    ztest = zone.add_parser("test", help="run a shortened recipe stage for real in a zone that is in observe mode")
    ztest.add_argument("zone")
    ztest.add_argument("--stage", help="recipe stage to run (default: the first that fits the zone)")
    ztest.add_argument("--speed", type=float, default=60.0, help="divide every duration in the stage by this")
    ztest.add_argument("--minutes", type=float, default=30.0, help="how long to run")
    broker(ztest)
    broker(sub.add_parser("commissioning", help="list what has been tested"))
    doctor = sub.add_parser("doctor", help="health check of a running installation, with the fix for each failure")
    broker(doctor)
    doctor.add_argument("--db", help="the hub's database file, to check storage")
    doctor.add_argument("--bundle", help="also write a diagnostics zip with secrets replaced")
    args = parser.parse_args(argv)

    root = find_repo_root(Path.cwd())
    try:
        catalog = Catalog.load(root)
    except ConfigError as err:
        print("catalog: INVALID")
        print("\n".join(f"  {p}" for p in err.problems))
        return 1
    try:
        handler = {"validate": _validate, "firmware": _firmware, "node": _node_test, "docs": _docs, "doctor": _doctor}.get(args.command, _commissioning)
        return handler(args, root, catalog)
    except ConfigError as err:
        print(f"site {getattr(args, 'site', '')}: INVALID")
        print("\n".join(f"  {p}" for p in err.problems))
        return 1


if __name__ == "__main__":
    sys.exit(main())
