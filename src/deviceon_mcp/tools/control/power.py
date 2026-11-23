"""Power control: shutdown / restart / sleep / hibernate / start (Wake-on-LAN)."""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

from ...actions import issue_action
from ...client import DeviceOnError
from ...deps import Deps
from ..common.devices import device_ref, get_device_checked, plugin_names
from . import wake
from .capabilities import power_plugin_needed, supported_power_actions

ACTION = "power"
PLUGIN = "power_onoff"

_WARNINGS = {
    "shutdown": "The device goes offline and stays off until someone powers it on (or Wake-on-LAN via action='start', if supported). Unsaved work on it is lost.",
    "restart": "The device reboots and is offline for a few minutes. Unsaved work and running programs on it are lost.",
    "sleep": "The device suspends and goes offline until woken up.",
    "hibernate": "The device hibernates and goes offline until powered on.",
    "start": "Sends Wake-on-LAN (the portal resends it every 10 s for up to 10 minutes). Works only if WOL is enabled "
             "in the device's BIOS/NIC and the relay shares its subnet.",
}


async def request_power_action(deps: Deps, did: int, action: str, reason: str = "") -> dict:
    if action not in _WARNINGS:
        raise ToolError(f"action must be one of {', '.join(_WARNINGS)}")
    dev = await get_device_checked(deps, did)
    online = bool(dev.get("connected"))
    if action == "start" and online:
        raise ToolError(f"device {did} is already online; 'start' (Wake-on-LAN) only works on an offline device.")
    if action != "start" and not online:
        raise ToolError(f"device {did} is offline; '{action}' needs a connected agent. Only 'start' works offline.")

    # Online actions are carried out by the agent's power_onoff plugin. 'start' is not: an offline device
    # reports no plugins at all, and the magic packet comes from the server or the relay agent.
    if power_plugin_needed(dev) and PLUGIN not in plugin_names(dev):
        raise ToolError(f"device {did} ({dev.get('name')}) has no '{PLUGIN}' plugin; install/enable it on the agent first.")

    warnings = [_WARNINGS[action]]
    supported, err = await supported_power_actions(deps, dev)
    if err:
        warnings.append(f"could not read the device's supported power actions ({err}); the portal will validate.")
    if supported and action not in supported:
        raise ToolError(f"device {did} supports only: {', '.join(supported)}.")

    summary = {"device": device_ref(dev), "power_action": action, "reason": reason or None}
    if action == "start":
        # DeviceOn silently sends nothing for wolmode 0 or an offline relay and reports failure 10 min later.
        wol = await wake.wol_status(deps, dev)
        if not wol["ready"]:
            raise ToolError(f"cannot wake device {did}: {wol.get('problem')}")
        summary["wake_via"] = wol.get("relay") or wol.get("relay_ip") or wol["mode"]
        if wol.get("note"):
            warnings.append(wol["note"])
    return await issue_action(deps, ACTION, {"did": did, "action": action}, summary, warnings)


async def execute(deps: Deps, params: dict) -> dict:
    try:
        resp = await deps.client.power_device(params["did"], params["action"])
    except DeviceOnError as ex:
        raise ToolError(f"power action failed: {ex}") from ex
    ok = resp.get("result") is not False
    if not ok:
        nxt = "The portal rejected the command; nothing happened on the device."
    elif params["action"] == "start":
        nxt = ("Wake-on-LAN requested. Call wait_for_device_online(did) to wait for the device to reconnect "
               "(usually 1-3 minutes).")
    else:
        nxt = ("The command was handed to the agent. Check list_devices / get_device_capabilities in a few "
               "minutes to see the device go offline (or come back online).")
    return {"status": "sent" if ok else "rejected", "portal_response": resp, "next_step": nxt}
