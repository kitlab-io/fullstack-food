"""Web dashboard service: a read-only HTTP API over the hub's database and live MQTT state."""

from .app import create_app
from .live import Live

__all__ = ["create_app", "Live"]
