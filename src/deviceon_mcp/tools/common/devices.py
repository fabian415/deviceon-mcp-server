"""Device lookup shared by every toolset."""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

from ...client import DeviceOnError
from ...deps import Deps

LIKE_FIELDS = ("name", "agentId", "mac", "localIP", "platformName", "osType", "osArch")


def plugin_names(dev: dict) -> list[str]:
    return [p.get("plugin") for p in dev.get("plugins") or [] if isinstance(p, dict) and p.get("plugin")]


_plugin_names = plugin_names  # backward-compatible private name


def require_online(dev: dict, what: str = "this action") -> None:
    if not dev.get("connected"):
        raise ToolError(f"device {dev.get('did')} ({dev.get('name')}) is offline; {what} needs a connected agent.")


def device_ref(dev: dict) -> dict:
    """Compact device identity for summaries."""
    return {"did": dev.get("did"), "name": dev.get("name"), "online": bool(dev.get("connected"))}


def compact_device(dev: dict) -> dict:
    plugins = _plugin_names(dev)
    return {
        "did": dev.get("did"),
        "name": dev.get("name"),
        "agentId": dev.get("agentId"),
        "connected": dev.get("connected"),
        "os": dev.get("ostype"),
        "localIp": dev.get("localip"),
        "cpu": dev.get("cpuname"),
        "groups": [g.get("name") for g in dev.get("devicegroups") or [] if isinstance(g, dict)],
        "canDiagnoseProcesses": "ProcessMonitor" in plugins,
    }


async def list_devices(
    deps: Deps,
    filter: str | None = None,
    field: str = "name",
    connected_only: bool = False,
    limit: int = 20,
) -> dict:
    if field not in LIKE_FIELDS:
        raise ToolError(f"field must be one of {', '.join(LIKE_FIELDS)}")
    limit = max(1, min(limit, 100))
    try:
        data = await deps.client.list_devices(
            like=filter or None,
            like_field=field,
            connected=True if connected_only else None,
            page_size=limit,
        )
    except DeviceOnError as ex:
        raise ToolError(str(ex)) from ex
    devices = [compact_device(d) for d in (data or {}).get("devices") or []]
    return {"total": (data or {}).get("total", len(devices)), "returned": len(devices), "devices": devices}


async def get_device_checked(deps: Deps, did: int, require_plugin: str | None = None) -> dict:
    """Fetch a device and fail with an actionable message if it can't be diagnosed."""
    try:
        dev = await deps.client.get_device(did)
    except DeviceOnError as ex:
        raise ToolError(f"cannot read device {did}: {ex}") from ex
    if require_plugin and require_plugin not in _plugin_names(dev):
        raise ToolError(
            f"device {did} ({dev.get('name')}) has no '{require_plugin}' plugin; "
            "install/enable it on the agent first."
        )
    return dev
