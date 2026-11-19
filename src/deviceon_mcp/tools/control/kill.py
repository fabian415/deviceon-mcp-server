"""Two-step guarded process kill: request_kill_process -> (user agrees) -> confirm_action.

Safety checks (unchanged from the original diagnose implementation):
- protected system/agent processes and pids are refused outright;
- the request re-reads a FRESH process list and checks pid + name;
- at confirm time the list is read again: if the pid exited or now belongs to another
  program, nothing is killed (already_exited / aborted_pid_reused); without fresh data
  nothing is killed either (aborted_no_fresh_data);
- after the kill, only full snapshots newer than the checked one count as proof it is gone.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp.exceptions import ToolError

from ...actions import issue_action
from ...client import DeviceOnError
from ...config import PROTECTED_PIDS
from ...deps import Deps
from ..common.devices import get_device_checked
from ..diagnose.processes import (
    KILL_ACTION, POLL_SEC, PROCESS_PLUGIN, _fresh_process_list, _newer, _read, _require_online, _same_name,
)

log = logging.getLogger("deviceon_mcp.audit")
ACTION = KILL_ACTION


async def request_kill_process(deps: Deps, did: int, pid: int, name: str, reason: str = "",
                               verify_timeout_sec: int = 30) -> dict:
    if pid in PROTECTED_PIDS or name.strip().lower() in deps.settings.protected_processes:
        raise ToolError(f"refused: '{name}' (pid {pid}) is a protected system/agent process and cannot be killed.")
    dev = await get_device_checked(deps, did, require_plugin=PROCESS_PLUGIN)
    _require_online(dev)
    snap = await _fresh_process_list(deps, dev, keep_alive_sec=deps.confirm.ttl_sec)
    proc = snap.procs.get(pid)
    if proc is None:
        raise ToolError(f"pid {pid} is not running on device {did}; it may have exited. Capture again.")
    if not _same_name(proc.name, name):
        raise ToolError(f"pid {pid} is now '{proc.name}', not '{name}'. The pid may have been reused; capture again.")
    if proc.name.strip().lower() in deps.settings.protected_processes:
        raise ToolError(f"refused: '{proc.name}' is a protected system/agent process.")

    summary = {
        "device": {"did": did, "name": dev.get("name")},
        "process": {"pid": pid, "name": proc.name, "owner": proc.owner, "cpu_now": proc.cpu,
                    "mem_mb": round(proc.mem_kb / 1024, 1) if proc.mem_kb else None},
        "system_cpu_now": snap.system_cpu,
        "reason": reason or None,
    }
    warnings = [f"Ends {proc.name} immediately; unsaved work in it is lost. If it is started by a schedule or "
                "service it may come back."]
    params = {"did": did, "pid": pid, "name": proc.name, "verify_timeout_sec": max(5, min(verify_timeout_sec, 120))}
    return await issue_action(deps, ACTION, params, summary, warnings)


async def execute(deps: Deps, params: dict) -> dict:
    did, pid, name = params["did"], params["pid"], params["name"]
    verify_timeout_sec = params.get("verify_timeout_sec", 30)
    base = {"pid": pid, "name": name}

    dev = await get_device_checked(deps, did, require_plugin=PROCESS_PLUGIN)
    _require_online(dev)
    # Never kill based on stale data: re-check against a fresh process list.
    try:
        snap = await _fresh_process_list(deps, dev, keep_alive_sec=verify_timeout_sec + 60)
    except ToolError as ex:
        log.warning("kill aborted (no fresh data) did=%s pid=%s: %s", did, pid, ex)
        return {**base, "status": "aborted_no_fresh_data", "killed": False, "detail": str(ex)}
    proc = snap.procs.get(pid)
    if proc is None:
        log.info("kill skipped (already exited) did=%s pid=%s", did, pid)
        return {**base, "status": "already_exited", "killed": False}
    if not _same_name(proc.name, name):
        log.warning("kill aborted (pid reused) did=%s pid=%s expected=%s actual=%s", did, pid, name, proc.name)
        return {**base, "status": "aborted_pid_reused", "killed": False,
                "detail": f"pid {pid} now belongs to '{proc.name}'. Nothing was killed."}

    cpu_before = snap.system_cpu
    try:
        resp = await deps.client.kill_processes(did, [pid])
    except DeviceOnError as ex:
        log.error("kill failed did=%s pid=%s: %s", did, pid, ex)
        return {**base, "status": "kill_failed", "killed": False, "detail": str(ex)}
    log.info("kill sent did=%s pid=%s name=%s response=%s", did, pid, name, resp)
    if resp.get("result") is False:
        return {**base, "status": "kill_failed", "killed": False, "detail": resp}

    # Verify only on full snapshots newer than the one we checked: a snapshot without
    # a process list says nothing about whether the pid is gone.
    waited, gone, last = 0.0, False, snap
    while waited < verify_timeout_sec:
        await deps.sleep(POLL_SEC)
        waited += POLL_SEC
        s = await _read(deps, dev)
        if not s.has_list or not _newer(s, last.ts_ms):
            continue
        last = s
        p = s.procs.get(pid)
        if p is None or not _same_name(p.name, name):
            gone = True
            break

    return {
        **base,
        "status": "killed" if gone else "kill_sent_unverified",
        "killed": gone,
        "system_cpu_before": cpu_before,
        "system_cpu_after": last.system_cpu if last is not snap else None,
        "next_step_hint": (
            "If the problem was periodic spikes, a low reading right now proves little: re-run "
            "analyze_metric_periodicity after at least one full period to confirm they stopped."
            if gone else
            f"No fresh process list showed the pid gone within {verify_timeout_sec}s. Check again later."
        ),
    }
