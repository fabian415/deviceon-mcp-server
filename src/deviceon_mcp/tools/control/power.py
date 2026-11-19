"""Power control: shutdown / restart / sleep / hibernate / start (Wake-on-LAN)."""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

from ...actions import issue_action
from ...client import DeviceOnError
from ...deps import Deps
from ..common.devices import device_ref, get_device_checked
from .capabilities import power_actions

ACTION = "power"
PLUGIN = "power_onoff"

_WARNINGS = {
    "shutdown": "The device goes offline and stays off until someone powers it on (or Wake-on-LAN via action='start', if supported). Unsaved work on it is lost.",
    "restart": "The device reboots and is offline for a few minutes. Unsaved work and running programs on it are lost.",
    "sleep": "The device suspends and goes offline until woken up.",
    "hibernate": "The device hibernates and goes offline until powered on.",
    "start": "Sends Wake-on-LAN. Works only if WOL is enabled on the device and a relay on its network can reach it.",
}


async def request_power_action(deps: Deps, did: int, action: str, reason: str = "") -> dict:
    if action not in _WARNINGS:
        raise ToolError(f"action must be one of {', '.join(_WARNINGS)}")
    dev = await get_device_checked(deps, did, require_plugin=PLUGIN)
    online = bool(dev.get("connected"))
    if action == "start" and online:
        raise ToolError(f"device {did} is already online; 'start' (Wake-on-LAN) only works on an offline device.")
    if action != "start" and not online:
        raise ToolError(f"device {did} is offline; '{action}' needs a connected agent. Only 'start' works offline.")

    warnings = [_WARNINGS[action]]
    try:
        supported = power_actions((await deps.client.get_power(did)).get("functionList"))
    except DeviceOnError as ex:
        supported = []
        warnings.append(f"could not read the device's supported power actions ({ex}); the portal will validate.")
    if supported and action not in supported:
        raise ToolError(f"device {did} supports only: {', '.join(supported)}.")

    summary = {"device": device_ref(dev), "power_action": action, "reason": reason or None}
    return await issue_action(deps, ACTION, {"did": did, "action": action}, summary, warnings)


async def execute(deps: Deps, params: dict) -> dict:
    try:
        resp = await deps.client.power_device(params["did"], params["action"])
    except DeviceOnError as ex:
        raise ToolError(f"power action failed: {ex}") from ex
    ok = resp.get("result") is not False
    return {
        "status": "sent" if ok else "rejected",
        "portal_response": resp,
        "next_step": ("The command was handed to the agent. Check list_devices / get_device_capabilities in a few "
                      "minutes to see the device go offline (or come back online)." if ok else
                      "The portal rejected the command; nothing happened on the device."),
    }
