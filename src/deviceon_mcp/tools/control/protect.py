"""Protection (application lock-down) and recovery (backup / restore) control."""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

from ...actions import issue_action
from ...client import DeviceOnError
from ...deps import Deps
from ..common.devices import device_ref, get_device_checked, require_online
from .capabilities import PROTECTION_TOKENS, RECOVERY_TOKENS, allowed_actions, suite_status

PROTECTION_ACTION = "protection"
RECOVERY_ACTION = "recovery"

_PROTECTION_WARNINGS = {
    "protect": "Turns protection on: the device is locked down so that only software already approved on it can "
               "run or change. New installs and updates will be blocked until it is unprotected.",
    "unprotect": "Turns protection off: the device can run and install any software again.",
    "install": "Installs the protection software on the device remotely; this may take a while and may restart it.",
    "update": "Updates the protection software on the device; this may restart it.",
    "activate": "Activates the protection software license on the device.",
}
_RECOVERY_WARNINGS = {
    "backup": "Creates a full system backup; it can take a long time and slow the device down meanwhile.",
    "recovery": "RESTORES THE SYSTEM FROM THE LATEST BACKUP: the device restarts and every change made since that "
                "backup (files, settings, installed software) is lost.",
    "install": "Installs the backup/recovery software on the device remotely; this may take a while and may restart it.",
    "update": "Updates the backup/recovery software on the device; this may restart it.",
    "activate": "Activates the backup/recovery software license on the device.",
}


def _check_suite(info: dict, action: str, mapping: dict[str, str], plugin: str, needs_install: set[str]) -> list[str]:
    allowed = allowed_actions(info.get("functionList"), mapping)
    if allowed and action not in allowed:
        raise ToolError(f"{plugin}: action '{action}' is not offered for this device; allowed: {', '.join(allowed)}.")
    if action in needs_install and not info.get("installed"):
        raise ToolError(f"{plugin} software is not installed on this device; request action='install' first.")
    if action in needs_install and info.get("activated") is False:
        raise ToolError(f"{plugin} software is not activated on this device; request action='activate' first.")
    warnings = []
    if info.get("expired"):
        warnings.append(f"the {plugin} license is marked expired; the portal may reject the action.")
    if info.get("lock") not in (None, "None", ""):
        warnings.append(f"device reports a pending {plugin} operation: {info.get('lock')}")
    return warnings


async def request_protection_action(deps: Deps, did: int, action: str, reason: str = "") -> dict:
    if action not in _PROTECTION_WARNINGS:
        raise ToolError(f"action must be one of {', '.join(_PROTECTION_WARNINGS)}")
    dev = await get_device_checked(deps, did, require_plugin="protection")
    require_online(dev, "protection control")
    try:
        info = await deps.client.get_protection(did)
    except DeviceOnError as ex:
        raise ToolError(f"cannot read protection status of device {did}: {ex}") from ex
    warnings = [_PROTECTION_WARNINGS[action], *_check_suite(info, action, PROTECTION_TOKENS, "protection",
                                                             {"protect", "unprotect"})]
    summary = {"device": device_ref(dev), "protection_action": action, "status": suite_status(info),
               "reason": reason or None}
    return await issue_action(deps, PROTECTION_ACTION, {"did": did, "action": action}, summary, warnings)


async def request_recovery_action(
    deps: Deps, did: int, action: str, remote: bool = False, asz_percent: int | None = None, reason: str = "",
) -> dict:
    if action not in _RECOVERY_WARNINGS:
        raise ToolError(f"action must be one of {', '.join(_RECOVERY_WARNINGS)}")
    if asz_percent is not None and (action != "install" or not 0 <= asz_percent <= 100):
        raise ToolError("asz_percent (0-100) is only valid with action='install'.")
    if remote and action not in ("backup", "recovery"):
        raise ToolError("remote is only valid with action='backup' or 'recovery'.")
    dev = await get_device_checked(deps, did, require_plugin="recovery")
    require_online(dev, "recovery control")
    try:
        info = await deps.client.get_recovery(did)
    except DeviceOnError as ex:
        raise ToolError(f"cannot read recovery status of device {did}: {ex}") from ex
    warnings = [_RECOVERY_WARNINGS[action], *_check_suite(info, action, RECOVERY_TOKENS, "recovery",
                                                           {"backup", "recovery"})]
    if action == "recovery" and remote:
        try:
            exists = await deps.client.has_remote_backup(dev["agentId"])
        except DeviceOnError as ex:
            raise ToolError(f"cannot check for a remote backup: {ex}") from ex
        if not exists:
            raise ToolError(f"device {did} has no remote backup to restore from.")

    params: dict = {"did": did, "action": action}
    if action in ("backup", "recovery"):
        params["remote"] = remote
    if asz_percent is not None:
        params["asz"] = asz_percent
    summary = {"device": device_ref(dev), "recovery_action": action, "remote": params.get("remote"),
               "asz_percent": asz_percent, "status": {**suite_status(info), "asz": info.get("asz")},
               "reason": reason or None}
    return await issue_action(deps, RECOVERY_ACTION, params, summary, warnings)


def _result(resp: dict, what: str) -> dict:
    ok = resp.get("result") is not False
    return {"status": "sent" if ok else "rejected", "portal_response": resp,
            "next_step": (f"The {what} command was handed to the agent; it runs asynchronously. Check "
                          "get_device_capabilities later for the new status." if ok else
                          "The portal rejected the command; nothing happened on the device.")}


async def execute_protection(deps: Deps, params: dict) -> dict:
    try:
        return _result(await deps.client.protection_device(params["did"], params["action"]), "protection")
    except DeviceOnError as ex:
        raise ToolError(f"protection action failed: {ex}") from ex


async def execute_recovery(deps: Deps, params: dict) -> dict:
    try:
        resp = await deps.client.recovery_device(params["did"], params["action"], params.get("remote"), params.get("asz"))
        return _result(resp, "recovery")
    except DeviceOnError as ex:
        raise ToolError(f"recovery action failed: {ex}") from ex
