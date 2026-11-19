"""Helpers for DeviceOn's SenML-like payloads.

Agent data is reported as nested objects with an "e" array of entries:
    {"bn": "System Monitor Info", "e": [{"n": "CPU Usage", "v": 2}, {"n": "Name", "sv": "x"}]}
Values live in "v" (number), "sv" (string) or "bv" (bool).
"""

from __future__ import annotations

from typing import Any

_SKIP_KEYS = {"_id", "ts", "opTS", "handler", "agentId", "connected"}


def entry_value(entry: dict) -> Any:
    for key in ("v", "sv", "bv"):
        if key in entry:
            return entry[key]
    return None


def entries_to_dict(e: list[dict] | None) -> dict[str, Any]:
    return {item.get("n"): entry_value(item) for item in (e or []) if isinstance(item, dict) and "n" in item}


def flatten_sensors(handler_obj: dict) -> dict[str, Any]:
    """Flatten one plugin's data into {"/Group/Sub/Name": value} using DeviceOn sensorId paths.

    Arrays of objects (e.g. the process list) are skipped; they are not sensors.
    """
    out: dict[str, Any] = {}

    def walk(obj: dict, prefix: str) -> None:
        for item in obj.get("e") or []:
            if isinstance(item, dict) and "n" in item:
                out[f"{prefix}/{item['n']}"] = entry_value(item)
        for key, val in obj.items():
            if key in _SKIP_KEYS or key == "e":
                continue
            if isinstance(val, dict):
                walk(val, f"{prefix}/{val.get('bn') or key}")

    walk(handler_obj or {}, "")
    return out


def flatten_sensor_meta(handler_obj: dict) -> dict[str, dict[str, Any]]:
    """Like flatten_sensors, but keeps each sensor's access mode.

    Returns {"/Group/Name": {"value": ..., "asm": "r" | "rw" | "w" | None}}. The access mode
    comes from the entry's "asm" or, failing that, the nearest enclosing group's "basm".
    """
    out: dict[str, dict[str, Any]] = {}

    def walk(obj: dict, prefix: str, inherited: str | None) -> None:
        group_asm = obj.get("basm") or inherited
        for item in obj.get("e") or []:
            if isinstance(item, dict) and "n" in item:
                asm = item.get("asm") or group_asm
                out[f"{prefix}/{item['n']}"] = {"value": entry_value(item), "asm": str(asm).lower() if asm else None}
        for key, val in obj.items():
            if key in _SKIP_KEYS or key == "e":
                continue
            if isinstance(val, dict):
                walk(val, f"{prefix}/{val.get('bn') or key}", group_asm)

    walk(handler_obj or {}, "", None)
    return out


def to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def snapshot_ts_ms(obj: dict) -> int | None:
    """Server-side write time: epoch millis, or {"$date": millis} in Mongo exports."""
    ts = obj.get("ts")
    if isinstance(ts, dict):
        ts = ts.get("$date")
    if isinstance(ts, str):
        try:
            ts = float(ts)
        except ValueError:
            return None
    if isinstance(ts, (int, float)):
        return int(ts)
    return None
