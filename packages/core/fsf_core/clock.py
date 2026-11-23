"""Clocks. Everything that needs the time takes a Clock so tests can run weeks in seconds."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Protocol

from . import topics


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class VirtualClock:
    """A clock that only moves when told to."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now += timedelta(seconds=seconds)
        return self._now


class BusClock:
    """Follows the time published by a simulator on the clock topic.

    Lets a hub in its own process run against an accelerated simulator.
    `now()` returns None until the first clock message arrives.
    """

    def __init__(self, bus, site_id: str):
        self._now: datetime | None = None
        bus.subscribe(topics.clock(site_id), self._on_clock)

    def _on_clock(self, topic: str, payload: bytes) -> None:
        self._now = datetime.fromisoformat(json.loads(payload)["t"])

    def now(self) -> datetime | None:
        return self._now
