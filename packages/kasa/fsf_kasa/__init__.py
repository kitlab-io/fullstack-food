"""Smart power strips as nodes: a bridge that speaks the MQTT contract for their outlets."""

from .bridge import MemoryBackend, PlugBridge, PlugError

__all__ = ["MemoryBackend", "PlugBridge", "PlugError"]
