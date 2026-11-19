"""Process tools: spike-correlated process capture, plus the snapshot helpers the kill tool
(control/kill.py) reuses.

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
from ...deps import Deps, ProgressFn
from ...senml import entries_to_dict, snapshot_ts_ms, to_number
from ..common.devices import get_device_checked

log = logging.getLogger("deviceon_mcp.audit")

PROCESS_PLUGIN = "ProcessMonitor"
KILL_ACTION = "kill_process"
MIN_SPIKE_SPREAD = 20.0  # system CPU percentage points between quiet and spike snapshots
# System memory must move by at least max(500 MB, 5% of RAM) to count as a spike. On the
# reference device (30 GB) idle usage drifts ~7% over an hour but far less within one capture.
MIN_MEM_SPREAD_MB = 500.0
MIN_MEM_SPREAD_RATIO = 0.05
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
    mem_used_mb: float | None = None   # totalPhysMemKB - availPhysMemKB
    mem_total_mb: float | None = None


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
    total_kb, avail_kb = to_number(system.get("totalPhysMemKB")), to_number(system.get("availPhysMemKB"))
    has_mem = bool(total_kb) and avail_kb is not None
    return Snapshot(
        snapshot_ts_ms(pm), to_number(system.get("CPU Usage")), procs, has_list=bool(procs),
        mem_used_mb=(total_kb - avail_kb) / 1024 if has_mem else None,  # type: ignore[operator]
        mem_total_mb=total_kb / 1024 if has_mem else None,  # type: ignore[operator]
    )


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

METRICS = ("cpu", "memory")
# Key that ranks processes while a spike was caught / when no spike was caught.
_SPIKE_KEY = {"cpu": "avg_cpu_during_spike", "memory": "spike_delta_mb"}
_CALM_KEY = {"cpu": "avg_cpu", "memory": "growth_mb"}
_AVG_KEY = {"cpu": "avg_cpu", "memory": "avg_mem_mb"}


def _sys_value(s: Snapshot, metric: str) -> float | None:
    return s.system_cpu if metric == "cpu" else s.mem_used_mb


def _proc_value(p: Proc, metric: str) -> float:
    return p.cpu if metric == "cpu" else (p.mem_kb or 0.0) / 1024


def _mean(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


def _mem_spread_threshold(snaps: list[Snapshot]) -> float:
    total = next((s.mem_total_mb for s in reversed(snaps) if s.mem_total_mb), None)
    return max(MIN_MEM_SPREAD_MB, MIN_MEM_SPREAD_RATIO * total) if total else MIN_MEM_SPREAD_MB


def _stats(series: list[float], system: list[float], high_idx: list[int], metric: str) -> dict:
    present = sum(1 for v in series if v > 0)
    corr = pearson(series, system)
    common = {
        "correlation": round(corr, 2) if corr is not None else None,
        "present_ratio": round(present / len(series), 2),
    }
    high = [series[i] for i in high_idx]
    if metric == "cpu":
        return {
            "avg_cpu": round(sum(series) / len(series), 1),
            "max_cpu": round(max(series), 1),
            "avg_cpu_during_spike": round(_mean(high), 1) if high else None,
            **common,
        }
    hs = set(high_idx)
    low = [v for i, v in enumerate(series) if i not in hs]
    delta = _mean(high) - _mean(low) if high and low else None  # type: ignore[operator]
    return {
        "avg_mem_mb": round(sum(series) / len(series), 1),
        "max_mem_mb": round(max(series), 1),
        "growth_mb": round(max(series) - min(series), 1),
        "spike_delta_mb": round(delta, 1) if delta is not None else None,
        **common,
    }


def _lifecycles(snaps: list[Snapshot]) -> dict[str, dict]:
    """Per process name: which pids were seen, how many ran at once, how often it was present."""
    out: dict[str, dict] = {}
    for s in snaps:
        here: dict[str, list[int]] = {}
        for p in s.procs.values():
            here.setdefault(p.name, []).append(p.pid)
        for name, pids in here.items():
            lc = out.setdefault(name, {"pids_seen": [], "max_concurrent": 0, "_present": 0})
            lc["_present"] += 1
            lc["max_concurrent"] = max(lc["max_concurrent"], len(pids))
            lc["pids_seen"].extend(p for p in sorted(pids) if p not in lc["pids_seen"])
    for lc in out.values():
        lc["present_ratio"] = round(lc.pop("_present") / len(snaps), 2)
        # New pid(s) over time but never two at once: the program is being restarted.
        lc["respawned"] = len(lc["pids_seen"]) > 1 and lc["max_concurrent"] == 1
    return out


def _recurrence_hint(lc: dict) -> str | None:
    if lc["respawned"]:
        what = f"ran as {len(lc['pids_seen'])} different pids one after another during the capture"
    elif lc["present_ratio"] < 1:
        what = "started or exited during the capture"
    else:
        return None
    return (
        f"this program {what}, so it is likely launched periodically (Task Scheduler, cron, a service "
        "restart or a parent process). Killing it only ends the current run, and the run may already have "
        "ended; tell the user to check what launches it on the device."
    )


async def capture_top_processes(
    deps: Deps,
    did: int,
    duration_sec: int = 60,
    samples: int = 12,
    top_n: int = 5,
    metric: str = "cpu",
    progress: ProgressFn | None = None,
) -> dict:
    metric = metric.strip().lower()
    if metric not in METRICS:
        raise ToolError(f"metric must be one of {', '.join(METRICS)}")
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
        "metric": metric,
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
    snaps: list[Snapshot] = [first] if _sys_value(first, metric) is not None else []
    seen_ts: set[int] = {first.ts_ms} if first.ts_ms is not None else set()
    skipped_partial = 0
    for i in range(1, samples):
        await deps.sleep(gap)
        snap = await _read(deps, dev)
        if not snap.has_list or not _newer(snap, baseline.ts_ms):
            skipped_partial += 1
        elif snap.ts_ms not in seen_ts and _sys_value(snap, metric) is not None:
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

    # 4. Did the capture catch a spike of the chosen metric?
    system = [_sys_value(s, metric) for s in snaps]  # type: ignore[misc]
    lo, hi = min(system), max(system)
    if metric == "cpu":
        spike_observed = hi - lo >= MIN_SPIKE_SPREAD
        result["system_cpu"] = {"min": lo, "max": hi, "spike_observed": spike_observed}
        if not spike_observed:
            result["notes"].append(
                f"system CPU varied only {hi - lo:.0f} points during capture; no spike was caught, so the "
                "ranking below reflects average load, not the spike. Re-run timed with next_peak_eta_sec."
            )
            mem = [s.mem_used_mb for s in snaps if s.mem_used_mb is not None]
            if mem and max(mem) - min(mem) >= _mem_spread_threshold(snaps):
                result["notes"].append(
                    f"system memory did change by {max(mem) - min(mem):.0f} MB during the capture; "
                    "if the anomaly is memory, re-run with metric='memory'."
                )
    else:
        threshold = _mem_spread_threshold(snaps)
        spike_observed = hi - lo >= threshold
        result["system_memory"] = {
            "min_used_mb": round(lo), "max_used_mb": round(hi),
            "total_mb": round(snaps[-1].mem_total_mb) if snaps[-1].mem_total_mb else None,
            "spike_threshold_mb": round(threshold), "spike_observed": spike_observed,
        }
        if not spike_observed:
            result["notes"].append(
                f"system memory varied only {hi - lo:.0f} MB during capture (< {threshold:.0f} MB); no rise was "
                "caught, so the ranking below reflects memory growth, not the spike. Use duration_sec >= period_sec."
            )
    high_idx = [i for i, v in enumerate(system) if v >= lo + (hi - lo) / 2] if spike_observed else []

    # 5. Rank. One row per (pid, name) so a reused pid is a different row, except programs that were
    #    restarted with a new pid: those are merged into one row per name. Concurrent same-name
    #    processes are also summed into top_process_groups.
    lifecycles = _lifecycles(snaps)
    respawned = {n for n, lc in lifecycles.items() if lc["respawned"]}
    rows = []
    for pid, name in {(pid, p.name) for s in snaps for pid, p in s.procs.items() if p.name not in respawned}:
        series = [_proc_value(s.procs[pid], metric) if pid in s.procs and s.procs[pid].name == name else 0.0
                  for s in snaps]
        if max(series) <= 0:
            continue
        latest = next((s.procs[pid] for s in reversed(snaps) if pid in s.procs and s.procs[pid].name == name), None)
        rows.append({"pid": pid, "name": name, "owner": latest.owner if latest else None,
                     **_stats(series, system, high_idx, metric)})

    by_name: dict[str, list[float]] = {}
    for idx, s in enumerate(snaps):
        for p in s.procs.values():
            by_name.setdefault(p.name, [0.0] * len(snaps))[idx] += _proc_value(p, metric)
    for name in respawned:
        series = by_name[name]
        if max(series) <= 0:
            continue
        latest = next(p for s in reversed(snaps) for p in s.procs.values() if p.name == name)
        rows.append({"pid": latest.pid, "pids_seen": lifecycles[name]["pids_seen"], "name": name,
                     "owner": latest.owner, **_stats(series, system, high_idx, metric),
                     # listed at all, not "using > 0" (a run that just started holds ~0 MB)
                     "present_ratio": lifecycles[name]["present_ratio"]})
    groups = [
        {"name": n, "instances": len(lifecycles[n]["pids_seen"]), **_stats(series, system, high_idx, metric)}
        for n, series in by_name.items()
        if lifecycles[n]["max_concurrent"] > 1 and max(series) > 0
    ]

    score = _SPIKE_KEY[metric] if spike_observed else _CALM_KEY[metric]
    avg = _AVG_KEY[metric]

    def rank(r: dict) -> tuple:
        # ties broken by average usage, then name/pid, so the order is stable across runs
        return (-(r[score] or 0), -(r["correlation"] or 0), -(r[avg] or 0), r["name"], r.get("pid", 0))

    rows.sort(key=rank)
    groups.sort(key=rank)
    result["top_processes"] = rows[:top_n]
    result["top_process_groups"] = groups[:top_n]

    # 6. Name a suspect only when the evidence is clear.
    suspect = None
    if spike_observed and rows:
        hs = set(high_idx)
        sys_high = _mean([system[i] for i in high_idx]) or 0.0
        sys_low = _mean([v for i, v in enumerate(system) if i not in hs])
        # What one process must explain: the spike level for CPU, the rise above the quiet level for memory.
        ref = sys_high if metric == "cpu" else sys_high - (sys_low if sys_low is not None else sys_high)
        best = rows[0]
        best_group = groups[0] if groups else None
        if best_group and (best_group[score] or 0) > 1.5 * (best[score] or 0) \
                and (best_group["correlation"] or 0) >= 0.6:
            suspect = {"type": "process_group", "name": best_group["name"],
                       "instances": best_group["instances"],
                       "reason": "several processes with the same name together drive the spikes; "
                                 "killing one pid may not stop it"}
        elif (best["correlation"] or 0) >= 0.6 and (best[score] or 0) >= 0.3 * ref:
            if metric == "cpu":
                reason = (f"its CPU tracks system CPU (r={best['correlation']}) and accounts for "
                          f"~{best['avg_cpu_during_spike']}% during spikes")
            else:
                reason = (f"its memory tracks system memory (r={best['correlation']}) and accounts for "
                          f"~{best['spike_delta_mb']:.0f} MB of the ~{ref:.0f} MB rise during spikes")
            suspect = {"type": "process", "pid": best["pid"], "name": best["name"], "reason": reason}
            if "pids_seen" in best:
                suspect["pids_seen"] = best["pids_seen"]
        if suspect:
            lc = lifecycles[suspect["name"]]
            hint = _recurrence_hint(lc)
            if hint:
                suspect["lifecycle"] = lc
                suspect["recurrence_hint"] = hint

        if metric == "memory" and ref > 0:
            # The agent may not report every process (e.g. system services): say how much is unexplained.
            # rows cover every listed pid (groups would double count them)
            explained = sum(max(0.0, r["spike_delta_mb"] or 0.0) for r in rows)
            ratio = explained / ref
            result["system_memory"]["spike_rise_mb"] = round(ref)
            result["system_memory"]["explained_by_listed_processes"] = round(min(ratio, 9.99), 2)
            if ratio < 0.5:
                result["notes"].append(
                    f"system memory rose ~{ref:.0f} MB during spikes but the listed processes account for only "
                    f"~{explained:.0f} MB. The cause may be a process the agent does not report (e.g. a system "
                    "service) or kernel/driver memory."
                )
    result["suspect"] = suspect
    if suspect is None and spike_observed:
        result["notes"].append("no single process clearly explains the spikes; review top_processes manually.")
    return result
