"""SQLite storage: sensor readings and their rollups, an event log, the decision trace,
commands with their acks, and planting progress.

Planting progress and dose events live here so a restarted hub resumes the right
stage and still honours daily watering caps. `retain()` keeps the file bounded: raw
readings, the decision trace and the command log are deleted after a set age, while
rollups and events are kept.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (t TEXT NOT NULL, device TEXT NOT NULL, quantity TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX IF NOT EXISTS readings_device_t ON readings (device, quantity, t);
CREATE INDEX IF NOT EXISTS readings_t ON readings (t);
CREATE TABLE IF NOT EXISTS rollups (res INTEGER NOT NULL, t TEXT NOT NULL, device TEXT NOT NULL, quantity TEXT NOT NULL,
    min REAL NOT NULL, mean REAL NOT NULL, max REAL NOT NULL, n INTEGER NOT NULL,
    PRIMARY KEY (res, device, quantity, t)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, t TEXT NOT NULL, kind TEXT NOT NULL, zone TEXT, planting TEXT,
    data TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'info');
CREATE INDEX IF NOT EXISTS events_kind_zone_t ON events (kind, zone, t);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, t TEXT NOT NULL, zone TEXT NOT NULL, loop TEXT NOT NULL,
    device TEXT NOT NULL, want INTEGER NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS decisions_zone_t ON decisions (zone, t);
CREATE INDEX IF NOT EXISTS decisions_t ON decisions (t);
CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, t TEXT NOT NULL, device TEXT NOT NULL, name TEXT NOT NULL,
    data TEXT NOT NULL, ack_t TEXT, ok INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS commands_device_t ON commands (device, t);
CREATE INDEX IF NOT EXISTS commands_t ON commands (t);
CREATE TABLE IF NOT EXISTS plantings (id TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

LEVELS = ("debug", "info", "warn", "error")
# Level an event kind gets when the caller does not pass one.
KIND_LEVELS = {"limit": "warn", "interlock": "warn", "command_rejected": "warn"}
ROLLUP_RESOLUTIONS = (300, 3600)    # seconds: 5-minute and hourly buckets


class Store:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path)
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        columns = [row[1] for row in self._db.execute("PRAGMA table_info(events)")]
        if columns and "level" not in columns:      # database written before events had levels
            self._db.execute("ALTER TABLE events ADD COLUMN level TEXT NOT NULL DEFAULT 'info'")
        self._db.executescript(SCHEMA)

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

    def rollups(self, device: str, quantity: str, res: int, since: datetime | None = None) -> list[dict]:
        """Min/mean/max per bucket of `res` seconds; `t` is the start of the bucket."""
        rows = self._db.execute(
            "SELECT t, min, mean, max, n FROM rollups WHERE res = ? AND device = ? AND quantity = ? AND t >= ? ORDER BY t",
            (res, device, quantity, since.isoformat() if since else ""))
        return [{"t": datetime.fromisoformat(t), "min": lo, "mean": mean, "max": hi, "n": n} for t, lo, mean, hi, n in rows]

    # -- events
    def event(self, t: datetime, kind: str, zone: str | None = None, planting: str | None = None,
              level: str | None = None, **data) -> None:
        level = level or KIND_LEVELS.get(kind, "info")
        if level not in LEVELS:
            raise ValueError(f"unknown event level {level!r}")
        self._db.execute("INSERT INTO events (t, kind, zone, planting, data, level) VALUES (?, ?, ?, ?, ?, ?)",
                         (t.isoformat(), kind, zone, planting, json.dumps(data), level))

    def events(self, kind: str | None = None, zone: str | None = None, since: datetime | None = None,
               min_level: str | None = None) -> list[dict]:
        query, args = "SELECT t, kind, zone, planting, data, level FROM events WHERE 1=1", []
        for column, value in (("kind", kind), ("zone", zone)):
            if value is not None:
                query += f" AND {column} = ?"
                args.append(value)
        if since is not None:
            query += " AND t >= ?"
            args.append(since.isoformat())
        if min_level is not None:
            wanted = LEVELS[LEVELS.index(min_level):]
            query += f" AND level IN ({', '.join('?' * len(wanted))})"
            args += wanted
        rows = self._db.execute(query + " ORDER BY id", args)
        return [{**json.loads(d), "t": datetime.fromisoformat(t), "kind": k, "zone": z, "planting": p, "level": lv}
                for t, k, z, p, d, lv in rows]

    # -- decision trace
    def decision(self, t: datetime, zone: str, loop: str, device: str, want: bool, action: str, reason: str,
                 inputs: dict) -> None:
        self._db.execute("INSERT INTO decisions (t, zone, loop, device, want, action, reason, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (t.isoformat(), zone, loop, device, int(want), action, reason, json.dumps(inputs)))

    def decisions(self, zone: str | None = None, loop: str | None = None, since: datetime | None = None) -> list[dict]:
        query, args = "SELECT t, zone, loop, device, want, action, reason, data FROM decisions WHERE 1=1", []
        for column, value in (("zone", zone), ("loop", loop)):
            if value is not None:
                query += f" AND {column} = ?"
                args.append(value)
        if since is not None:
            query += " AND t >= ?"
            args.append(since.isoformat())
        rows = self._db.execute(query + " ORDER BY id", args)
        return [{"t": datetime.fromisoformat(t), "zone": z, "loop": lp, "device": dev, "want": bool(w), "action": a,
                 "reason": r, "inputs": json.loads(d)} for t, z, lp, dev, w, a, r, d in rows]

    # -- commands and acks
    def command(self, t: datetime, command_id: str, device: str, name: str, data: dict) -> None:
        self._db.execute("INSERT OR REPLACE INTO commands (id, t, device, name, data) VALUES (?, ?, ?, ?, ?)",
                         (command_id, t.isoformat(), device, name, json.dumps(data)))

    def ack(self, t: datetime, command_id: str, ok: bool, error: str | None = None) -> bool:
        """Attach an ack to the command it answers. False when no such command was sent from here."""
        cursor = self._db.execute("UPDATE commands SET ack_t = ?, ok = ?, error = ? WHERE id = ? AND ack_t IS NULL",
                                  (t.isoformat(), int(ok), error, command_id))
        return cursor.rowcount > 0

    def commands(self, device: str | None = None, since: datetime | None = None, unacked: bool = False) -> list[dict]:
        query, args = "SELECT id, t, device, name, data, ack_t, ok, error FROM commands WHERE 1=1", []
        if device is not None:
            query += " AND device = ?"
            args.append(device)
        if since is not None:
            query += " AND t >= ?"
            args.append(since.isoformat())
        if unacked:
            query += " AND ack_t IS NULL"
        rows = self._db.execute(query + " ORDER BY t, rowid", args)
        return [{"id": i, "t": datetime.fromisoformat(t), "device": dev, "name": n, "data": json.loads(d),
                 "ack_t": datetime.fromisoformat(at) if at else None, "ok": None if ok is None else bool(ok), "error": err}
                for i, t, dev, n, d, at, ok, err in rows]

    # -- planting progress
    def load_planting(self, planting_id: str) -> dict | None:
        row = self._db.execute("SELECT state FROM plantings WHERE id = ?", (planting_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_planting(self, planting_id: str, state: dict) -> None:
        self._db.execute("INSERT INTO plantings (id, state) VALUES (?, ?) "
                         "ON CONFLICT(id) DO UPDATE SET state = excluded.state", (planting_id, json.dumps(state)))
        self._db.commit()

    # -- small durable values (pauses, overrides, rollup watermark)
    def get_setting(self, key: str, default=None):
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value) -> None:
        self._db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
        self._db.commit()

    # -- retention
    def retain(self, now: datetime, raw_readings: float, decision_trace: float) -> None:
        """Roll readings up into 5-minute and hourly buckets, then drop what has aged out.

        raw_readings and decision_trace are ages in seconds. Only whole hours are rolled
        up, so a bucket is never written from part of its samples.
        """
        upto = now.replace(minute=0, second=0, microsecond=0)
        done = self.get_setting("rollup_until", "")
        if upto.isoformat() > done:
            for res in ROLLUP_RESOLUTIONS:
                self._db.execute(
                    "INSERT OR REPLACE INTO rollups (res, t, device, quantity, min, mean, max, n) "
                    "SELECT ?1, strftime('%Y-%m-%dT%H:%M:%S+00:00', CAST(strftime('%s', t) AS INTEGER) / ?1 * ?1, 'unixepoch') AS bucket, "
                    "device, quantity, MIN(value), AVG(value), MAX(value), COUNT(*) "
                    "FROM readings WHERE t >= ?2 AND t < ?3 GROUP BY bucket, device, quantity",
                    (res, done, upto.isoformat()))
            self.set_setting("rollup_until", upto.isoformat())
        # Never delete a reading that has not been rolled up yet.
        raw_cutoff = min(now - timedelta(seconds=raw_readings), upto).isoformat()
        trace_cutoff = (now - timedelta(seconds=decision_trace)).isoformat()
        self._db.execute("DELETE FROM readings WHERE t < ?", (raw_cutoff,))
        self._db.execute("DELETE FROM decisions WHERE t < ?", (trace_cutoff,))
        self._db.execute("DELETE FROM commands WHERE t < ?", (trace_cutoff,))
        self._db.commit()

    def counts(self) -> dict[str, int]:
        return {table: self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("readings", "rollups", "events", "decisions", "commands")}
