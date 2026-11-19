"""Metric tools: periodic-spike analysis over history, and current readings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp.exceptions import ToolError

from ...analysis import analyze_periodicity
from ...client import DeviceOnError
from ...deps import Deps
from ...senml import flatten_sensors, to_number
from ..common.devices import _plugin_names, get_device_checked

CPU_PLUGIN = "ProcessMonitor"
CPU_SENSOR = "/System Monitor Info/CPU Usage"
MEM_TOTAL_SENSOR = "/System Monitor Info/totalPhysMemKB"
MEM_AVAIL_SENSOR = "/System Monitor Info/availPhysMemKB"
MEM_USAGE_SENSOR = "/System Monitor Info/usagePhysMem"  # percent, stored in history like CPU Usage
HIST_MAX_SAMPLES = 10_000  # DeviceOn histdata caps `amount` at 10000

# Plugins that typically carry hardware temperatures (SUSI / hardware monitor).
_TEMP_PLUGIN_HINTS = ("susi", "hwm", "hardware", "thermal", "temperature")


async def find_temperatures(deps: Deps, dev: dict) -> tuple[str | None, dict[str, float]]:
    """Return (plugin, {sensorId: value}) of temperature readings, or (None, {})."""
    did, agent_id = dev["did"], dev["agentId"]
    s = deps.settings
    if s.temp_plugin and s.temp_sensor:
        data = await deps.client.get_latest_data(did, agent_id, s.temp_plugin, s.temp_sensor)
        flat = flatten_sensors(data.get(s.temp_plugin) or {})
        vals = {k: v for k, v in ((k, to_number(v)) for k, v in flat.items()) if v is not None}
        return s.temp_plugin, vals

    candidates = [p for p in _plugin_names(dev) if any(h in p.lower() for h in _TEMP_PLUGIN_HINTS)]
    for plugin in candidates:
        try:
            data = await deps.client.get_latest_data(did, agent_id, plugin)
        except DeviceOnError:
            continue
        flat = flatten_sensors(data.get(plugin) or {})
        temps = {
            k: n
            for k, v in flat.items()
            if "temp" in k.lower() and (n := to_number(v)) is not None
        }
        if temps:
            return plugin, temps
    return None, {}


def _pick_cpu_temp(temps: dict[str, float]) -> str | None:
    for k in temps:
        if "cpu" in k.lower():
            return k
    return next(iter(temps), None)


async def resolve_sensor(deps: Deps, dev: dict, sensor: str) -> tuple[str, str]:
    """Map 'cpu' / 'memory' / 'temperature' / '<plugin>:<sensorId>' to (plugin, sensorId)."""
    key = sensor.strip()
    if key.lower() == "cpu":
        return CPU_PLUGIN, CPU_SENSOR
    if key.lower() in ("memory", "mem"):
        return CPU_PLUGIN, MEM_USAGE_SENSOR
    if key.lower() in ("temperature", "temp"):
        plugin, temps = await find_temperatures(deps, dev)
        chosen = _pick_cpu_temp(temps)
        if not plugin or not chosen:
            raise ToolError(
                "no temperature sensor found on this device (needs a SUSI / hardware-monitor plugin; "
                "VMs usually have none). Use sensor='cpu' instead."
            )
        return plugin, chosen
    if ":" in key:
        plugin, sensor_id = key.split(":", 1)
        if not sensor_id.startswith("/"):
            raise ToolError("sensorId must start with '/', e.g. 'ProcessMonitor:/System Monitor Info/CPU Usage'")
        return plugin, sensor_id
    raise ToolError("sensor must be 'cpu', 'memory', 'temperature', or '<plugin>:<sensorId>'")


async def analyze_metric_periodicity(
    deps: Deps,
    did: int,
    sensor: str = "cpu",
    window_min: int = 30,
    min_amplitude: float = 20.0,
) -> dict:
    window_min = max(5, min(window_min, 1440))
    dev = await get_device_checked(deps, did)
    plugin, sensor_id = await resolve_sensor(deps, dev, sensor)

    now_ms = deps.now_ms()
    end = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    begin = end - timedelta(minutes=window_min)
    try:
        # newest first: if the window holds more than HIST_MAX_SAMPLES, the OLDEST samples
        # are the ones dropped (analyze_periodicity re-sorts by time anyway).
        items = await deps.client.get_hist_data(
            did, dev["agentId"], plugin, sensor_id, begin, end, amount=HIST_MAX_SAMPLES, order="desc"
        )
    except DeviceOnError as ex:
        raise ToolError(
            f"cannot read history for {plugin}:{sensor_id}: {ex}. "
            "Make sure the sensor is enabled for history storage on this device."
        ) from ex

    points = []
    for it in items:
        if it.get("sensorId") not in (None, sensor_id):
            continue
        v, ts = to_number(it.get("v")), it.get("ts")
        if v is not None and isinstance(ts, (int, float)):
            points.append((int(ts), v))

    result = analyze_periodicity(points, now_ms, window_min * 60_000, min_amplitude=min_amplitude)
    result = {
        "device": {"did": did, "name": dev.get("name"), "connected": dev.get("connected")},
        "sensor": f"{plugin}:{sensor_id}",
        "window_min": window_min,
        **result,
    }
    if len(items) >= HIST_MAX_SAMPLES:
        result["notes"].append(
            f"history capped at the newest {HIST_MAX_SAMPLES} samples; the start of the window is not covered. "
            "Use a smaller window_min for full coverage."
        )
    if not dev.get("connected"):
        result["notes"].append("device is currently offline.")
    if result.get("periodic"):
        is_mem = plugin == CPU_PLUGIN and "PhysMem" in sensor_id
        result["next_step_hint"] = (
            f"Call capture_top_processes with metric='{'memory' if is_mem else 'cpu'}' and "
            "duration_sec >= period_sec so the capture spans a spike."
        )
    return result


async def get_current_metrics(deps: Deps, did: int) -> dict:
    dev = await get_device_checked(deps, did)
    out: dict = {
        "device": {"did": did, "name": dev.get("name"), "connected": dev.get("connected")},
        "cpu_usage_pct": None,
        "memory": None,
        "temperatures": None,
        "notes": [],
    }
    if CPU_PLUGIN in _plugin_names(dev):
        try:
            # Periodic auto-report copy: the live copy may be a stale leftover of an
            # earlier intermittent report.
            data = await deps.client.get_latest_data(did, dev["agentId"], CPU_PLUGIN, source="autoreport")
            flat = flatten_sensors(data.get(CPU_PLUGIN) or {})
            out["cpu_usage_pct"] = to_number(flat.get(CPU_SENSOR))
            total, avail = to_number(flat.get(MEM_TOTAL_SENSOR)), to_number(flat.get(MEM_AVAIL_SENSOR))
            if total and avail is not None:
                out["memory"] = {
                    "total_mb": round(total / 1024),
                    "available_mb": round(avail / 1024),
                    "used_pct": round((1 - avail / total) * 100, 1),
                }
        except DeviceOnError as ex:
            out["notes"].append(f"cpu/memory unavailable: {ex}")
    else:
        out["notes"].append("no ProcessMonitor plugin: cpu/memory unavailable.")

    try:
        plugin, temps = await find_temperatures(deps, dev)
    except DeviceOnError as ex:
        plugin, temps = None, {}
        out["notes"].append(f"temperature lookup failed: {ex}")
    if temps:
        out["temperatures"] = {"plugin": plugin, "readings_c": dict(list(temps.items())[:10])}
    else:
        out["notes"].append("no temperature sensor found (needs SUSI / hardware-monitor plugin).")
    if not dev.get("connected"):
        out["notes"].append("device is offline; values are the last reported ones.")
    return out
