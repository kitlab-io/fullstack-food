"""Duration strings used throughout the YAML files: 30s, 5m, 2h, 14d, and compounds such as 1h30m."""

import re

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_PART = re.compile(r"\s*([0-9]+(?:\.[0-9]+)?)([smhd])")


def seconds(value: str | int | float | None, default: float | None = None) -> float:
    """Convert a duration string (or a bare number of seconds) to seconds."""
    if value is None:
        if default is None:
            raise ValueError("duration is required")
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    text, total, at = value.strip(), 0.0, 0
    while at < len(text):
        part = _PART.match(text, at)
        if not part:
            break
        total += float(part.group(1)) * _UNITS[part.group(2)]
        at = part.end()
    if not text or at < len(text):
        raise ValueError(f"invalid duration {value!r}: expected a number followed by s, m, h or d")
    return total
