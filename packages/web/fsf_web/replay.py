"""The dashboard over a finished scenario run instead of a live site.

The run happened in this process: its bus still holds the last state of every zone and
device, its clock stands at the end of the run, and its database is on disk. So the usual
pages, charts, log and decision trace work unchanged. Nothing can be switched: the pages
are open for reading and there is no login to act with.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from .app import create_app
from .auth import Auth
from .live import Live


def app_for_run(result, static_dir: Path | None = None) -> FastAPI:
    """`result` is a ScenarioResult that kept its system (`run_scenario(..., out_dir=..., keep_system=True)`)."""
    system = result.system
    if system is None or result.db_path is None:
        raise ValueError("the run must keep its system and write its database: out_dir=..., keep_system=True")
    live = Live(system.site.id, system.bus, system.clock)       # receives the retained state of the finished run
    return create_app(system.site, system.catalog, result.db_path, live, static_dir,
                      auth=Auth(read_without_login=True), scenario=result.to_dict())


def serve_run(result, port: int = 8081, static_dir: Path | None = None) -> None:
    import uvicorn

    print(f"scenario {result.id}: http://127.0.0.1:{port} (read-only; Ctrl+C to stop)", flush=True)
    uvicorn.run(app_for_run(result, static_dir), host="127.0.0.1", port=port, log_level="warning")
