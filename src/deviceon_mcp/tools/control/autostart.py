"""Stop a program from starting automatically: disable a scheduled task or a service (two-step).

Both changes are reversible (Enable-ScheduledTask / Set-Service -StartupType <old>), which is
why only these two kinds are offered; deleting Run-key values or files is left to people or to
toolset 'remote'. The scripts are fixed and built from validated names, run as SYSTEM through
the terminal. Windows' own tasks (\\Microsoft\\...), shared svchost services and anything
belonging to the DeviceOn agent or a protected process are refused.
"""

from __future__ import annotations

import re

from mcp.server.fastmcp.exceptions import ToolError

from ...actions import issue_action
from ...deps import Deps
from ...remote_exec import RemoteExecError, run_json_probe
from ..common.devices import device_ref, get_device_checked, require_online

ACTION = "disable_autostart"
KINDS = ("scheduled_task", "service")
_TASK = re.compile(r"^\\(?:[^\\/:*?\"<>|']+\\)*[^\\/:*?\"<>|']+$")
_SERVICE = re.compile(r"^[A-Za-z0-9_.\- ]{1,80}$")
# Agent binaries / install folder. Not plain "deviceon": the PoC's own \DeviceOnSim\ tasks must stay disable-able.
_AGENT_HINTS = ("cagent", "wiseagent", "wise-agent", "saagent", "\\advantech\\")


def _split_task(path: str) -> tuple[str, str]:
    folder, _, name = path.rpartition("\\")
    return folder + "\\", name


def _state_script(kind: str, name: str) -> str:
    if kind == "scheduled_task":
        folder, task = _split_task(name)
        return (f"#DOMCP:autostart-state\n$t=Get-ScheduledTask -TaskPath '{folder}' -TaskName '{task}' -EA SilentlyContinue\n"
                "$r=if($t){@{exists=$true;state=[string]$t.State;user=$t.Principal.UserId;"
                "run=(@($t.Actions|%{(\"$($_.Execute) $($_.Arguments)\").Trim()}) -join ' | ');"
                "exe=@($t.Actions|%{[Environment]::ExpandEnvironmentVariables([string]$_.Execute)})}}else{@{exists=$false}}")
    return (f"#DOMCP:autostart-state\n$v=Get-CimInstance Win32_Service -Filter \"Name='{name}'\" -EA SilentlyContinue\n"
            "$r=if($v){@{exists=$true;state=$v.State;start=$v.StartMode;display=$v.DisplayName;path=$v.PathName}}"
            "else{@{exists=$false}}")


def _disable_script(kind: str, name: str, stop: bool) -> str:
    if kind == "scheduled_task":
        folder, task = _split_task(name)
        q = f"-TaskPath '{folder}' -TaskName '{task}'"
        return ("#DOMCP:autostart-disable\n$r=try{" + (f"Stop-ScheduledTask {q} -EA SilentlyContinue;" if stop else "")
                + f"Disable-ScheduledTask {q} -EA Stop|Out-Null;$t=Get-ScheduledTask {q};"
                "$exe=@($t.Actions|%{[Environment]::ExpandEnvironmentVariables([string]$_.Execute)});"
                + ("Start-Sleep -Seconds 2;" if stop else "")
                + "$left=@(Get-Process -EA SilentlyContinue|?{$_.Path -and $exe -contains $_.Path}|%{$_.Id});"
                "@{state=[string]$t.State;still_running_pids=$left}}catch{@{error=$_.Exception.Message}}")
    return ("#DOMCP:autostart-disable\n$r=try{" + (f"Stop-Service -Name '{name}' -Force -EA Stop;" if stop else "")
            + f"Set-Service -Name '{name}' -StartupType Disabled -EA Stop;"
            f"$v=Get-CimInstance Win32_Service -Filter \"Name='{name}'\";@{{state=$v.State;start=$v.StartMode}}"
            "}catch{@{error=$_.Exception.Message}}")


async def _probe(deps: Deps, dev: dict, script: str) -> dict:
    try:
        return await run_json_probe(deps, dev, script, 60) or {}
    except RemoteExecError as ex:
        raise ToolError(f"could not reach the device: {ex}") from ex


def _refuse_reason(deps: Deps, kind: str, name: str, state: dict) -> str | None:
    text = " ".join(str(state.get(k) or "") for k in ("run", "path", "exe", "display")).lower() + " " + name.lower()
    if kind == "scheduled_task" and name.lower().startswith("\\microsoft\\"):
        return "it is a built-in Windows task (\\Microsoft\\...)"
    if kind == "service" and "svchost.exe" in text:
        return "it is a shared Windows service hosted in svchost.exe"
    hit = next((h for h in _AGENT_HINTS if h in text), None)
    if hit:
        return f"it belongs to the DeviceOn/WISE agent ({hit}); disabling it would cut the device off"
    prot = next((p for p in deps.settings.protected_processes if len(p) > 4 and re.search(rf"\b{re.escape(p)}\b", text)), None)
    if prot:
        return f"it runs a protected process ({prot})"
    return None


async def request_disable_autostart(deps: Deps, did: int, kind: str, name: str, stop_running: bool = True,
                                    reason: str = "") -> dict:
    if kind not in KINDS:
        raise ToolError(f"kind must be one of {', '.join(KINDS)}")
    name = name.strip()
    if kind == "scheduled_task" and not _TASK.match(name):
        raise ToolError("name must be the full task path as find_process_autostart returns it, e.g. '\\Vendor\\Updater'")
    if kind == "service" and not _SERVICE.match(name):
        raise ToolError("name must be the service's short name (Name, not DisplayName), e.g. 'VendorSvc'")
    dev = await get_device_checked(deps, did)
    require_online(dev, "changing autostart settings")
    state = await _probe(deps, dev, _state_script(kind, name))
    if not state.get("exists"):
        raise ToolError(f"{kind.replace('_', ' ')} {name!r} does not exist on the device.")
    why = _refuse_reason(deps, kind, name, state)
    if why:
        raise ToolError(f"refusing to disable {name!r}: {why}.")
    if kind == "scheduled_task":
        folder, task = _split_task(name)
        will = ["stop its running instance (Stop-ScheduledTask)"] if stop_running else []
        will.append("disable the task so it no longer starts at its triggers (e.g. at boot)")
        undo = f"Enable-ScheduledTask -TaskPath '{folder}' -TaskName '{task}'"
    else:
        will = ["stop the service"] if stop_running else []
        will.append("set its startup type to Disabled")
        undo = f"Set-Service -Name '{name}' -StartupType {state.get('start') or 'Automatic'}; Start-Service '{name}'"
    summary = {"device": device_ref(dev), "kind": kind, "name": name, "current": state, "will": will,
               "undo": undo, "reason": reason or None}
    warnings = ["The program will no longer start automatically, including after the next reboot. "
                "If it is needed for production, fix it (e.g. update the leaking program) and re-enable it."]
    if str(state.get("user") or "").upper() in ("SYSTEM", "NT AUTHORITY\\SYSTEM", "S-1-5-18"):
        warnings.append("It runs as SYSTEM, so only an administrator can re-enable it.")
    params = {"did": did, "kind": kind, "name": name, "stop": bool(stop_running)}
    return await issue_action(deps, ACTION, params, summary, warnings)


async def execute(deps: Deps, params: dict) -> dict:
    dev = await get_device_checked(deps, params["did"])
    require_online(dev, "changing autostart settings")
    res = await _probe(deps, dev, _disable_script(params["kind"], params["name"], params["stop"]))
    if res.get("error"):
        raise ToolError(f"the device refused the change: {res['error']}")
    out = {"status": "disabled", "result": res}
    if res.get("still_running_pids"):
        out["next_step"] = (f"The task is disabled but its program still runs (pid {res['still_running_pids']}); "
                            "stop it with request_kill_process.")
    else:
        out["next_step"] = "Done. Watch memory with get_current_metrics / analyze_metric_periodicity to confirm."
    return out
