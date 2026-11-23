"""What can be controlled on a device: one read-only call the agent makes before choosing a tool."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from ...client import DeviceOnError
from ...deps import Deps
from ..common.devices import device_ref, get_device_checked, plugin_names
from .wake import wol_status

# DeviceOn action -> tokens that may appear in the device's power functionList.
# PowerCtrl checks "suspend" for sleep and the agent reports "wol" for Wake-on-LAN.
POWER_TOKENS: dict[str, tuple[str, ...]] = {
    "shutdown": ("shutdown",),
    "restart": ("restart",),
    "sleep": ("suspend", "sleep"),
    "hibernate": ("hibernate",),
    "start": ("wol", "start"),
}
# protection / recovery action -> token in their functionList
PROTECTION_TOKENS = {"protect": "protect", "unprotect": "unprotect", "install": "remoteinstall",
                     "update": "remoteupdate", "activate": "remoteactivate"}
RECOVERY_TOKENS = {"backup": "backup", "recovery": "recovery", "install": "remoteinstall",
                   "update": "remoteupdate", "activate": "remoteactivate"}


def split_functions(function_list: Any) -> set[str]:
    return {t.strip().lower() for t in str(function_list or "").split(",") if t.strip()}


def power_actions(function_list: Any) -> list[str]:
    tokens = split_functions(function_list)
    return [a for a, names in POWER_TOKENS.items() if tokens & set(names)]


def allowed_actions(function_list: Any, mapping: dict[str, str]) -> list[str]:
    tokens = split_functions(function_list)
    return [a for a, t in mapping.items() if t in tokens]


def suite_status(info: dict) -> dict:
    """Status fields shared by the protection and recovery responses."""
    return {k: info.get(k) for k in ("installed", "activated", "expired", "status", "lock", "actionmsg", "warningmsg")
            if k in info}


async def _safe(fn: Callable[[], Awaitable[Any]]) -> tuple[Any, str | None]:
    try:
        return await fn(), None
    except DeviceOnError as ex:
        return None, str(ex)


async def supported_power_actions(deps: Deps, dev: dict) -> tuple[list[str], str | None]:
    """Power actions the device supports: the power API's functionList, else the one on the device record.

    The device record keeps functionList while the device is offline, which is exactly when 'start' matters.
    """
    power, err = await _safe(lambda: deps.client.get_power(dev["did"]))
    actions = power_actions((power or {}).get("functionList"))
    if not actions:
        actions = power_actions(dev.get("functionList"))
    return actions, (err if not actions else None)


def power_plugin_needed(dev: dict) -> bool:
    """Only an online device needs the power_onoff plugin.

    An offline device reports an empty plugin list, and Wake-on-LAN is sent by the server or a relay
    agent, never by the sleeping device itself.
    """
    return bool(dev.get("connected"))


async def get_device_capabilities(deps: Deps, did: int) -> dict:
    dev = await get_device_checked(deps, did)
    plugins = plugin_names(dev)
    online = bool(dev.get("connected"))
    agent_id = dev["agentId"]
    tools: dict[str, Any] = {}
    notes: list[str] = []

    if "power_onoff" in plugins or not power_plugin_needed(dev):
        actions, err = await supported_power_actions(deps, dev)
        usable = [a for a in actions if (a == "start") != online]
        tools["request_power_action"] = {
            "available": bool(usable), "supported_actions": actions, "usable_now": usable,
            **({"error": err} if err else {}),
        }
        if "start" in actions:
            tools["wake_on_lan"] = await wol_status(deps, dev)
    else:
        tools["request_power_action"] = {"available": False, "reason": "no power_onoff plugin"}

    tools["take_screenshot"] = {"available": "screenshot" in plugins and online,
                                **({} if "screenshot" in plugins else {"reason": "no screenshot plugin"})}
    tools["request_set_data"] = {"available": online, "plugins": plugins,
                                 "note": "only sensors whose access mode allows writing (asm contains 'w') can be set"}
    tools["request_kvm_session"] = {"available": "remote_kvm" in plugins and online,
                                    **({} if "remote_kvm" in plugins else {"reason": "no remote_kvm plugin"})}

    for name, plugin, getter, mapping in (
        ("request_protection_action", "protection", deps.client.get_protection, PROTECTION_TOKENS),
        ("request_recovery_action", "recovery", deps.client.get_recovery, RECOVERY_TOKENS),
    ):
        if plugin not in plugins:
            tools[name] = {"available": False, "reason": f"no {plugin} plugin"}
            continue
        info, err = await _safe(lambda g=getter: g(did))
        info = info or {}
        entry: dict[str, Any] = {"available": online and bool(info), "allowed_actions": allowed_actions(info.get("functionList"), mapping),
                                 "status": suite_status(info)}
        if plugin == "recovery":
            entry["asz"] = info.get("asz")
            entry["remote_backup_exists"], _ = await _safe(lambda: deps.client.has_remote_backup(agent_id))
        if err:
            entry["error"] = err
        if info and not info.get("installed"):
            entry["note"] = f"{plugin} software is not installed; only 'install' (and 'activate'/'update') make sense"
        if info.get("expired"):
            notes.append(f"{plugin} license is expired; actions may be rejected by the portal")
        tools[name] = entry

    if "Syslog" in plugins:
        events, err = await _safe(lambda: deps.client.devlog_event_types(agent_id))
        tools["device_log"] = {"available": bool(events), "event_types": events or [], **({"error": err} if err else {})}
    else:
        tools["device_log"] = {"available": False, "reason": "no Syslog plugin"}

    tools["remote_command"] = {"launch_process": "ProcessMonitor" in plugins, "terminal": "terminal" in plugins}
    if not online:
        notes.append("device is offline, so DeviceOn reports no plugins for it; the 'no ... plugin' reasons above "
                     "may only mean 'offline'. Re-check after it is back online.")
        notes.append("device is offline: only request_power_action(action='start') can work "
                     "(see tools.wake_on_lan; find_wol_relay_candidates helps pick a relay)")
    return {"device": {**device_ref(dev), "os": dev.get("ostype")}, "plugins": plugins, "tools": tools, "notes": notes}
