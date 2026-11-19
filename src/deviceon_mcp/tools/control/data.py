"""Write sensor / setting values through a plugin (PUT /devicectrl/data)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from ...actions import issue_action
from ...client import DeviceOnError
from ...deps import Deps
from ...senml import flatten_sensor_meta
from ..common.devices import device_ref, get_device_checked, plugin_names, require_online

ACTION = "set_data"
MAX_SENSORS = 20


def _coerce(sensor: str, new: Any, current: Any) -> Any:
    """Match the new value's JSON type to the current one where that is unambiguous."""
    if current is None:
        return new
    if isinstance(current, bool):
        if isinstance(new, bool):
            return new
        if isinstance(new, str) and new.strip().lower() in ("true", "false"):
            return new.strip().lower() == "true"
        raise ToolError(f"{sensor} is boolean (now {current}); give true or false, not {new!r}.")
    if isinstance(current, (int, float)):
        if isinstance(new, bool):
            raise ToolError(f"{sensor} is numeric (now {current}); give a number, not {new!r}.")
        if isinstance(new, (int, float)):
            return new
        try:
            return float(new) if "." in str(new) else int(new)
        except ValueError as ex:
            raise ToolError(f"{sensor} is numeric (now {current}); {new!r} is not a number.") from ex
    return new if isinstance(new, str) else str(new)


def senml_entry(sensor: str, value: Any) -> dict:
    if isinstance(value, bool):
        return {"n": sensor, "bv": value}
    if isinstance(value, (int, float)):
        return {"n": sensor, "v": value}
    return {"n": sensor, "sv": str(value)}


async def request_set_data(deps: Deps, did: int, plugin: str, values: dict[str, Any], reason: str = "") -> dict:
    if not values:
        raise ToolError("values is empty; give {sensorId: newValue}.")
    if len(values) > MAX_SENSORS:
        raise ToolError(f"at most {MAX_SENSORS} sensors per request.")
    dev = await get_device_checked(deps, did)
    require_online(dev, "setting data")
    if plugin not in plugin_names(dev):
        raise ToolError(f"device {did} has no plugin '{plugin}'. Plugins: {', '.join(plugin_names(dev))}")

    warnings: list[str] = []
    try:
        latest = await deps.client.get_latest_data(did, dev["agentId"], plugin)
        meta = flatten_sensor_meta((latest or {}).get(plugin) or {})
    except DeviceOnError as ex:
        meta = {}
        warnings.append(f"could not read current values ({ex}); sensor ids and types are NOT verified.")
    if not meta and not warnings:
        warnings.append(f"plugin '{plugin}' reported no data; sensor ids and types are NOT verified.")

    changes = []
    for sensor, new in values.items():
        if not sensor.startswith("/"):
            raise ToolError(f"sensor id must be a path like '/Group/Name', got {sensor!r}.")
        m = meta.get(sensor)
        if meta and m is None:
            writable = [s for s, v in meta.items() if v["asm"] and "w" in v["asm"]][:20]
            raise ToolError(f"plugin '{plugin}' has no sensor {sensor!r}. Writable sensors: {writable or 'none found'}")
        if m and m["asm"] and "w" not in m["asm"]:
            raise ToolError(f"{sensor} is read-only (access mode '{m['asm']}').")
        if m and m["asm"] is None:
            warnings.append(f"{sensor}: access mode unknown; the agent may reject the write.")
        current = m["value"] if m else None
        changes.append({"sensor": sensor, "current": current, "new": _coerce(sensor, new, current)})

    summary = {"device": device_ref(dev), "plugin": plugin, "changes": changes, "reason": reason or None}
    params = {"did": did, "agent_id": dev["agentId"], "plugin": plugin,
              "entries": [senml_entry(c["sensor"], c["new"]) for c in changes]}
    return await issue_action(deps, ACTION, params, summary, warnings)


async def execute(deps: Deps, params: dict) -> dict:
    try:
        resp = await deps.client.set_data(params["agent_id"], params["plugin"], params["entries"])
    except DeviceOnError as ex:
        raise ToolError(f"set data failed: {ex}") from ex
    items = resp.get("items") or []
    results = [{"sensor_path": i.get("sensorPath"), "status_code": i.get("statusCode"), "message": i.get("sv")}
               for i in items if isinstance(i, dict)]
    ok = bool(results) and all(r["status_code"] == 200 for r in results)
    return {"status": "ok" if ok else "partial_or_failed", "results": results}
