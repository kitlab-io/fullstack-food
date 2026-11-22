"""`python -m fsf_core validate [site ...]` checks the catalog and site files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import Catalog, ConfigError, find_repo_root, load_site


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fsf_core")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate the catalog and site files")
    validate.add_argument("sites", nargs="*", help="site directories or files (default: sites/examples/*)")
    validate.add_argument("--pins", action="store_true", help="also propose pins for devices that have none assigned")
    args = parser.parse_args(argv)

    root = find_repo_root(Path.cwd())
    try:
        catalog = Catalog.load(root)
    except ConfigError as err:
        print("catalog: INVALID")
        print("\n".join(f"  {p}" for p in err.problems))
        return 1
    counts = ", ".join(f"{len(v)} {k.lower()}" for k, v in catalog.items.items())
    print(f"catalog: ok ({counts})")

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


if __name__ == "__main__":
    sys.exit(main())
