"""Process tools: spike-correlated process capture and two-step guarded kill.

How DeviceOn delivers process lists (verified in WebApp/Worker source):
- The periodic auto-report usually carries only "System Monitor Info" (CPU/memory),
  stored in plugin_latest_raw_data. No process list.
- The full list ("Process Monitor Info") is only uploaded on demand: PUT
  /devicectrl/intermittent_report makes the agent upload the whole plugin every N
  seconds for a while (commCmd 533 -> 534), stored in plugin_live_data and read by
  GET /data/devices/{did}/latestdata without sensorId.
- plugin_live_data keeps the LAST intermittent upload forever, so a snapshot is only
  trusted if its server timestamp is newer than what we saw before triggering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from mcp.server.fastmcp.exceptions import ToolError

from ...analysis import pearson
from ...client import DeviceOnError
from ...config import PROTECTED_PIDS
from ...deps import Deps, ProgressFn
from ...senml import entries_to_dict, snapshot_ts_ms, to_number
from ..common.devices import get_device_checked

log = logging.getLogger("deviceon_mcp.audit")

PROCESS_PLUGIN = "ProcessMonitor"
KILL_ACTION = "kill_process"
MIN_SPIKE_SPREAD = 20.0  # system CPU percentage points between quiet and spike snapshots
POLL_SEC = 2  # how often we read the live snapshot while waiting for fresh data


@dataclass
class Proc:
    pid: int
    name: str
    owner: str | None
    cpu: float
    mem_kb: float | None


@dataclass
class Snapshot:
    ts_ms: int | None
    system_cpu: float | None
    procs: dict[int, Proc]
    has_list: bool  # False when the report carried no process list (e.g. periodic auto-report)


def parse_snapshot(pm: dict) -> Snapshot:
    raw_list = pm.get("Process Monitor Info")
    procs: dict[int, Proc] = {}
    for item in raw_list if isinstance(raw_list, list) else []:
        if not isinstance(item, dict):
            continue
        e = entries_to_dict(item.get("e"))
        pid = to_number(e.get("PID"))
        if pid is None:
            continue
        procs[int(pid)] = Proc(
            pid=int(pid),
            name=str(e.get("Name") or ""),
            owner=e.get("Owner"),
            cpu=to_number(e.get("CPU Usage")) or 0.0,
            mem_kb=to_number(e.get("Mem Usage")),
        )
    system = entries_to_dict((pm.get("System Monitor Info") or {}).get("e"))
    return Snapshot(snapshot_ts_ms(pm), to_number(system.get("CPU Usage")), procs, has_list=bool(procs))


async def _read(deps: Deps, dev: dict) -> Snapshot:
    try:
        return parse_snapshot(await deps.client.get_process_snapshot(dev["did"], dev["agentId"]))
    except DeviceOnError as ex:
        raise ToolError(f"cannot read process data of device {dev['did']}: {ex}") from ex


def _newer(snap: Snapshot, after_ts: int | None) -> bool:
    if snap.ts_ms is None:
        return False
    return after_ts is None or snap.ts_ms > after_ts


async def _start_live_report(deps: Deps, dev: dict, interval_sec: int, timeout_sec: int) -> dict:
    """Ask the agent for full ProcessMonitor uploads. Never raises; returns what happened."""
    info = {"requested": False, "interval_sec": interval_sec, "timeout_sec": timeout_sec}
    try:
        resp = await deps.client.start_intermittent_report(dev["agentId"], PROCESS_PLUGIN, interval_sec, timeout_sec)
        info["requested"] = resp.get("result") is not False
        if not info["requested"]:
            info["error"] = f"portal returned {resp}"
    except DeviceOnError as ex:
        info["error"] = str(ex)
        log.warning("intermittent_report failed did=%s: %s", dev["did"], ex)
    return info


async def _wait_fresh(deps: Deps, dev: dict, after_ts: int | None, wait_sec: float) -> Snapshot | None:
    """Poll until a snapshot with a process list newer than after_ts arrives."""
    waited = 0.0
    while True:
        snap = await _read(deps, dev)
        if snap.has_list and _newer(snap, after_ts):
            return snap
        if waited >= wait_sec:
            return None
        await deps.sleep(POLL_SEC)
        waited += POLL_SEC


async def _fresh_process_list(deps: Deps, dev: dict, keep_alive_sec: int = 60) -> Snapshot:
    """Trigger a live report and return the first fresh full snapshot, or raise."""
    baseline = await _read(deps, dev)
    info = await _start_live_report(deps, dev, POLL_SEC, keep_alive_sec)
    snap = await _wait_fresh(deps, dev, baseline.ts_ms, wait_sec=20)
    if snap is None:
        hint = f" (intermittent_report failed: {info['error']})" if "error" in info else ""
        raise ToolError(f"could not obtain a fresh process list from device {dev['did']}{hint}.")
    return snap


def _same_name(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    return a == b or a == b + ".exe" or b == a + ".exe"


def _require_online(dev: dict) -> None:
    if not dev.get("connected"):
        raise ToolError(f"device {dev['did']} ({dev.get('name')}) is offline; process data needs a connected agent.")


# --------------------------------------------------------------------------
# capture_top_processes
# --------------------------------------------------------------------------


def _stats(series: list[float], system: list[float], high_idx: list[int]) -> dict:
    present = sum(1 for v in series if v > 0)
    corr = pearson(series, system)
    return {
        "avg_cpu": round(sum(series) / len(series), 1),
        "max_cpu": round(max(series), 1),
        "avg_cpu_during_spike": round(sum(series[i] for i in high_idx) / len(high_idx), 1) if high_idx else None,
        "correlation": round(corr, 2) if corr is not None else None,
        "present_ratio": round(present / len(series), 2),
    }


async def capture_top_processes(
    deps: Deps,
    did: int,
    duration_sec: int = 60,
    samples: int = 12,
    top_n: int = 5,
    progress: ProgressFn | None = None,
) -> dict:
    duration_sec = max(5, min(duration_sec, 600))
    samples = max(3, min(samples, 60))
    top_n = max(1, min(top_n, 20))
    dev = await get_device_checked(deps, did, require_plugin=PROCESS_PLUGIN)
    _require_online(dev)
    gap = max(1.0, duration_sec / (samples - 1))

    # 1. Ask the agent for full uploads at roughly our sampling pace.
    baseline = await _read(deps, dev)
    report_interval = int(max(2, min(10, round(gap))))
    warmup_sec = max(15, 3 * report_interval)
    live = await _start_live_report(deps, dev, report_interval, duration_sec + warmup_sec + 30)

    result: dict = {
        "device": {"did": did, "name": dev.get("name")},
        "intermittent_report": live,
        "requested_samples": samples,
        "notes": [],
    }

    # 2. Wait for the first upload newer than anything we saw before (not counted as a sample).
    first = await _wait_fresh(deps, dev, baseline.ts_ms, warmup_sec)
    if first is None:
        result.update(process_list_available=False, unique_snapshots=0, suspect=None)
        if "error" in live:
            result["notes"].append(
                f"could not request a full process report: {live['error']}. The service account needs the "
                "GetSensor permission on this device."
            )
        else:
            result["notes"].append(
                f"requested a full ProcessMonitor report but no fresh process list arrived within {warmup_sec}s. "
                "Check the agent's ProcessMonitor plugin and connectivity."
            )
        return result
    result["process_list_available"] = True

    # 3. Sample. Keep only full snapshots with a server timestamp we haven't seen.
    snaps: list[Snapshot] = [first] if first.system_cpu is not None else []
    seen_ts: set[int] = {first.ts_ms} if first.ts_ms is not None else set()
    skipped_partial = 0
    for i in range(1, samples):
        await deps.sleep(gap)
        snap = await _read(deps, dev)
        if not snap.has_list or not _newer(snap, baseline.ts_ms):
            skipped_partial += 1
        elif snap.ts_ms not in seen_ts and snap.system_cpu is not None:
            seen_ts.add(snap.ts_ms)  # type: ignore[arg-type]
            snaps.append(snap)
        if progress:
            await progress(i + 1, samples, f"snapshot {i + 1}/{samples} ({len(snaps)} unique)")

    result["unique_snapshots"] = len(snaps)
    if skipped_partial:
        result["skipped_without_process_list"] = skipped_partial
    if len(snaps) < 3:
        result["notes"].append(
            "fewer than 3 distinct process snapshots; increase duration_sec or reduce samples."
        )
        if not snaps:
            result["suspect"] = None
            return result

    system = [s.system_cpu for s in snaps]  # type: ignore[misc]
    lo, hi = min(system), max(system)
    spike_observed = hi - lo >= MIN_SPIKE_SPREAD
    high_idx = [i for i, v in enumerate(system) if v >= lo + (hi - lo) / 2] if spike_observed else []
    result["system_cpu"] = {"min": lo, "max": hi, "spike_observed": spike_observed}
    if not spike_observed:
        result["notes"].append(
            f"system CPU varied only {hi - lo:.0f} points during capture; no spike was caught, so the "
            "ranking below reflects average load, not the spike. Re-run timed with next_peak_eta_sec."
        )

    # Per process (pid+name, so a reused pid is a different row) and per name (multi-process programs).
    keys = {(pid, p.name) for s in snaps for pid, p in s.procs.items()}
    rows = []
    for pid, name in keys:
        series = [s.procs[pid].cpu if pid in s.procs and s.procs[pid].name == name else 0.0 for s in snaps]
        if max(series) <= 0:
            continue
        latest = next((s.procs[pid] for s in reversed(snaps) if pid in s.procs and s.procs[pid].name == name), None)
        rows.append({"pid": pid, "name": name, "owner": latest.owner if latest else None,
                     **_stats(series, system, high_idx)})

    by_name: dict[str, list[float]] = {}
    counts: dict[str, set[int]] = {}
    for idx, s in enumerate(snaps):
        for p in s.procs.values():
            by_name.setdefault(p.name, [0.0] * len(snaps))[idx] += p.cpu
            counts.setdefault(p.name, set()).add(p.pid)
    groups = [
        {"name": n, "instances": len(counts[n]), **_stats(series, system, high_idx)}
        for n, series in by_name.items()
        if len(counts[n]) > 1 and max(series) > 0
    ]

    sort_key = (lambda r: (r["avg_cpu_during_spike"] or 0, r["correlation"] or 0)) if spike_observed \
        else (lambda r: (r["avg_cpu"], r["correlation"] or 0))
    rows.sort(key=sort_key, reverse=True)
    groups.sort(key=sort_key, reverse=True)
    result["top_processes"] = rows[:top_n]
    result["top_process_groups"] = groups[:top_n]

    # Name a suspect only when the evidence is clear.
    suspect = None
    if spike_observed and rows:
        best = rows[0]
        spike_sys = sum(system[i] for i in high_idx) / len(high_idx)
        best_group = groups[0] if groups else None
        if best_group and (best_group["avg_cpu_during_spike"] or 0) > 1.5 * (best["avg_cpu_during_spike"] or 0) \
                and (best_group["correlation"] or 0) >= 0.6:
            suspect = {"type": "process_group", "name": best_group["name"],
                       "instances": best_group["instances"],
                       "reason": "several processes with the same name together drive the spikes; "
                                 "killing one pid may not stop it"}
        elif (best["correlation"] or 0) >= 0.6 and (best["avg_cpu_during_spike"] or 0) >= 0.3 * spike_sys:
            suspect = {"type": "process", "pid": best["pid"], "name": best["name"],
                       "reason": f"its CPU tracks system CPU (r={best['correlation']}) and accounts for "
                                 f"~{best['avg_cpu_during_spike']}% during spikes"}
    result["suspect"] = suspect
    if suspect is None and spike_observed:
        result["notes"].append("no single process clearly explains the spikes; review top_processes manually.")
    return result


# --------------------------------------------------------------------------
# request_kill_process / confirm_kill_process
# --------------------------------------------------------------------------


async def request_kill_process(deps: Deps, did: int, pid: int, name: str, reason: str = "") -> dict:
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
    token = deps.confirm.issue(KILL_ACTION, {"did": did, "pid": pid, "name": proc.name}, summary)
    log.info("kill requested did=%s pid=%s name=%s reason=%r", did, pid, proc.name, reason)
    return {
        "confirm_token": token,
        "expires_in_sec": deps.confirm.ttl_sec,
        "summary": summary,
        "instruction": (
            "Nothing has been killed. Show this summary to the user and ask for explicit confirmation. "
            "Call confirm_kill_process with this token ONLY after the user agrees; if they decline, do nothing."
        ),
    }


async def confirm_kill_process(deps: Deps, confirm_token: str, verify_timeout_sec: int = 30) -> dict:
    try:
        pending = deps.confirm.consume(confirm_token, KILL_ACTION)
    except KeyError as ex:
        raise ToolError(f"{ex.args[0]}. Call request_kill_process again.") from ex
    did, pid, name = pending.params["did"], pending.params["pid"], pending.params["name"]
    base = {"device": pending.summary.get("device"), "pid": pid, "name": name}
    verify_timeout_sec = max(5, min(verify_timeout_sec, 120))

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
            "Spikes are periodic, so a low reading right now proves little. Re-run "
            "analyze_metric_periodicity after at least one full period to confirm they stopped."
            if gone else
            f"No fresh process list showed the pid gone within {verify_timeout_sec}s. Check again later."
        ),
    }
