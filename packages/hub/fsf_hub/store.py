"""SQLite storage: sensor readings, an event log, and planting progress.

Planting progress and dose events live here so a restarted hub resumes the right
stage and still honours daily watering caps.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (t TEXT NOT NULL, device TEXT NOT NULL, quantity TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX IF NOT EXISTS readings_device_t ON readings (device, quantity, t);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, t TEXT NOT NULL, kind TEXT NOT NULL, zone TEXT, planting TEXT, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_kind_zone_t ON events (kind, zone, t);
CREATE TABLE IF NOT EXISTS plantings (id TEXT PRIMARY KEY, state TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path)
        self._db.executescript(SCHEMA)
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    def commit(self) -> None:
        self._db.commit()

    # -- readings
    def reading(self, t: datetime, device: str, quantity: str, value: float) -> None:
        self._db.execute("INSERT INTO readings VALUES (?, ?, ?, ?)", (t.isoformat(), device, quantity, value))

    def readings(self, device: str, quantity: str, since: datetime | None = None) -> list[tuple[datetime, float]]:
        rows = self._db.execute(
            "SELECT t, value FROM readings WHERE device = ? AND quantity = ? AND t >= ? ORDER BY t",
            (device, quantity, since.isoformat() if since else ""))
        return [(datetime.fromisoformat(t), v) for t, v in rows]

    # -- events
    def event(self, t: datetime, kind: str, zone: str | None = None, planting: str | None = None, **data) -> None:
        self._db.execute("INSERT INTO events (t, kind, zone, planting, data) VALUES (?, ?, ?, ?, ?)",
                         (t.isoformat(), kind, zone, planting, json.dumps(data)))

    def events(self, kind: str | None = None, zone: str | None = None, since: datetime | None = None) -> list[dict]:
        query, args = "SELECT t, kind, zone, planting, data FROM events WHERE 1=1", []
        for column, value in (("kind", kind), ("zone", zone)):
            if value is not None:
                query += f" AND {column} = ?"
                args.append(value)
        if since is not None:
            query += " AND t >= ?"
            args.append(since.isoformat())
        rows = self._db.execute(query + " ORDER BY id", args)
        return [{"t": datetime.fromisoformat(t), "kind": k, "zone": z, "planting": p, **json.loads(d)}
                for t, k, z, p, d in rows]

    # -- planting progress
    def load_planting(self, planting_id: str) -> dict | None:
        row = self._db.execute("SELECT state FROM plantings WHERE id = ?", (planting_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_planting(self, planting_id: str, state: dict) -> None:
        self._db.execute("INSERT INTO plantings (id, state) VALUES (?, ?) "
                         "ON CONFLICT(id) DO UPDATE SET state = excluded.state", (planting_id, json.dumps(state)))
        self._db.commit()
