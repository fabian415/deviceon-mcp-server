"""Device lookup shared by every toolset."""

from __future__ import annotations

from datetime import datetime

from mcp.server.fastmcp.exceptions import ToolError

from ...client import DeviceOnError
from ...deps import Deps

LIKE_FIELDS = ("name", "agentId", "mac", "localIP", "platformName", "osType", "osArch")

# DeviceOn's wolmode values (Portal labels: 未設定 / 直接喚醒模式 / 代理模式 / 中繼器模式).
WOL_MODES = {0: "not_set", 1: "direct", 2: "agent", 3: "repeater"}


def agent_id(dev: dict) -> str | None:
    """Device detail responses spell it 'agentId', list entries 'agentid'."""
    return dev.get("agentId") or dev.get("agentid")


def plugin_names(dev: dict) -> list[str]:
    return [p.get("plugin") for p in dev.get("plugins") or [] if isinstance(p, dict) and p.get("plugin")]


_plugin_names = plugin_names  # backward-compatible private name


def require_online(dev: dict, what: str = "this action") -> None:
    if not dev.get("connected"):
        raise ToolError(f"device {dev.get('did')} ({dev.get('name')}) is offline; {what} needs a connected agent.")


def device_ref(dev: dict) -> dict:
    """Compact device identity for summaries."""
    return {"did": dev.get("did"), "name": dev.get("name"), "online": bool(dev.get("connected"))}


def wol_brief(dev: dict) -> dict | None:
    """Wake-on-LAN config as stored on the device record (list and detail responses carry it)."""
    if "wolmode" not in dev:
        return None
    mode = dev.get("wolmode") or 0
    out: dict = {"mode": WOL_MODES.get(mode, str(mode))}
    if mode in (2, 3):
        out["relay"] = dev.get("wolrepeatername") or dev.get("wolrepeater")
    return out


def ms_to_local_iso(ms) -> str | None:
    """Epoch milliseconds -> ISO-8601 in the MCP host's local time zone (with offset)."""
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="seconds")


def compact_device(dev: dict) -> dict:
    plugins = _plugin_names(dev)
    out = {
        "did": dev.get("did"),
        "name": dev.get("name"),
        "agentId": agent_id(dev),
        "connected": dev.get("connected"),
        "os": dev.get("ostype"),
        "localIp": dev.get("localip"),
        "cpu": dev.get("cpuname"),
        "groups": [g.get("name") for g in dev.get("devicegroups") or [] if isinstance(g, dict)],
        "canDiagnoseProcesses": "ProcessMonitor" in plugins,
        # DeviceOn's logints: set each time the agent connects (not updated on disconnect).
        "lastConnectedAt": ms_to_local_iso(dev.get("login_unix_ts")),
    }
    wol = wol_brief(dev)
    if wol:
        out["wakeOnLan"] = wol
    return out


async def list_devices(
    deps: Deps,
    filter: str | None = None,
    field: str = "name",
    connected_only: bool = False,
    limit: int = 20,
    offline_only: bool = False,
    recent_first: bool = False,
) -> dict:
    if connected_only and offline_only:
        raise ToolError("connected_only and offline_only cannot both be true")
    if field not in LIKE_FIELDS:
        raise ToolError(f"field must be one of {', '.join(LIKE_FIELDS)}")
    limit = max(1, min(limit, 100))
    try:
        data = await deps.client.list_devices(
            like=filter or None,
            like_field=field,
            connected=True if connected_only else (False if offline_only else None),
            page_size=limit,
            order_by="logints" if recent_first else None,
            order_type="desc",
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
        if not dev.get("connected"):
            # An offline device reports no plugins at all, so "missing plugin" would be misleading.
            raise ToolError(
                f"device {did} ({dev.get('name')}) is offline; its plugins (incl. '{require_plugin}') "
                "are only known while it is connected. Bring it online first."
            )
        raise ToolError(
            f"device {did} ({dev.get('name')}) has no '{require_plugin}' plugin; "
            "install/enable it on the agent first."
        )
    return dev
