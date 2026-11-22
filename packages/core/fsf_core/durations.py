"""Duration strings used throughout the YAML files: 30s, 5m, 2h, 14d."""

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def seconds(value: str | int | float | None, default: float | None = None) -> float:
    """Convert a duration string (or a bare number of seconds) to seconds."""
    if value is None:
        if default is None:
            raise ValueError("duration is required")
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    if not text or text[-1] not in _UNITS:
        raise ValueError(f"invalid duration {value!r}: expected a number followed by s, m, h or d")
    return float(text[:-1]) * _UNITS[text[-1]]
