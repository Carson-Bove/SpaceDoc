"""Simulated-time offsets written the way clerks write them: "T+0", "T+30m", "T+1d6h".

Offsets are measured from scenario start (the moment the presentation happens). Durations use
the same units without the "T+" prefix: "10h", "2d".
"""

from __future__ import annotations

import re

_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_DURATION = re.compile(
    r"^(?:(\d+(?:\.\d+)?)d)?(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?$"
)


def parse_duration(text: str) -> float:
    """'1d6h' -> 108000.0 seconds. '0' is allowed. Raises ValueError otherwise."""
    text = text.strip().replace(" ", "")
    if text == "0":
        return 0.0
    m = _DURATION.match(text)
    if not text or not m or not any(m.groups()):
        raise ValueError(f"not a duration: {text!r} (use e.g. 30m, 8h, 2d, 1d6h)")
    return sum(float(v) * u for v, u in zip(m.groups(), _UNITS.values(), strict=True) if v)


def parse_offset(text: str) -> float:
    """'T+8h' -> 28800.0 seconds after scenario start."""
    text = text.strip().replace(" ", "")
    if not text.upper().startswith("T+"):
        raise ValueError(f"not a time offset: {text!r} (use e.g. T+0, T+30m, T+1d6h)")
    return parse_duration(text[2:])


def format_offset(seconds: float) -> str:
    """28800 -> 'T+8h'. Inverse of parse_offset for whole seconds."""
    rest = int(round(seconds))
    if rest == 0:
        return "T+0"
    parts = []
    for unit, size in _UNITS.items():
        n, rest = divmod(rest, size)
        if n:
            parts.append(f"{n}{unit}")
    return "T+" + "".join(parts)
