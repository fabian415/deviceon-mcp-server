"""Watch the raw per-process fields the DeviceOn agent reports, e.g. to learn what IsActive means.

Keeps an intermittent ProcessMonitor report running on one device and prints every fresh
snapshot: all fields of the processes whose name matches --name, plus every process whose
IsActive is not true. Use it together with simulator/windows-hang/hang_app.exe:

    1. start the probe:       python scripts/probe_process_fields.py --device MYPC --name hang_app --duration 180
    2. on the device:          hang_app.exe --after 60
    3. watch IsActive of hang_app before / after the window turns "Not Responding"

Reading the result:
  - IsActive flips to false once the window hangs   -> it reflects window responsiveness; usable for diagnosis
  - IsActive stays true while the window is hung    -> it only means "process alive"; the agent cannot report hangs
  - windowless processes (services) are false        -> it may mean "has a responsive window"; check the list

Needs the same environment variables as the MCP server (DEVICEON_BASE_URL plus
DEVICEON_TOKEN or DEVICEON_USERNAME/DEVICEON_PASSWORD). Read-only apart from starting the
intermittent report; it never kills anything.

Options: --did N | --device NAME   target device (exactly one)
         --name TEXT               case-insensitive substring of the process name to show in full
         --duration SEC            how long to watch (default 180)
         --interval SEC            agent upload interval (default 5)
         --jsonl PATH              also append every fresh raw snapshot to this file
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from deviceon_mcp.client import DeviceOnClient, DeviceOnError  # noqa: E402
from deviceon_mcp.config import Settings  # noqa: E402
from deviceon_mcp.senml import entries_to_dict, snapshot_ts_ms  # noqa: E402

PLUGIN = "ProcessMonitor"
KEEP_ALIVE_SEC = 60   # each intermittent_report request lasts this long ...
RENEW_EVERY_SEC = 45  # ... and is renewed before it runs out


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--did", type=int, help="device id")
    target.add_argument("--device", help="device name (substring match, must be unique)")
    ap.add_argument("--name", default="hang_app", help="process name substring to show in full (default hang_app)")
    ap.add_argument("--duration", type=int, default=180, help="seconds to watch (default 180)")
    ap.add_argument("--interval", type=int, default=5, help="agent upload interval in seconds (default 5)")
    ap.add_argument("--jsonl", help="append every fresh raw ProcessMonitor snapshot to this file")
    args = ap.parse_args()
    if args.duration <= 0 or args.interval <= 0:
        ap.error("--duration and --interval must be positive")
    return args


async def resolve_device(client: DeviceOnClient, did: int | None, name: str | None) -> dict:
    if did is not None:
        return await client.get_device(did)
    data = await client.list_devices(like=name, like_field="name", page_size=20)
    devices = (data or {}).get("devices") or []
    exact = [d for d in devices if str(d.get("name", "")).lower() == name.lower()]  # type: ignore[union-attr]
    if len(exact) == 1:
        devices = exact
    if len(devices) != 1:
        found = ", ".join(f"{d.get('name')} (did={d.get('did')})" for d in devices) or "none"
        raise SystemExit(f"--device '{name}' must match exactly one device; found: {found}")
    return await client.get_device(devices[0]["did"])


def processes(pm: dict) -> list[dict]:
    out = []
    for item in pm.get("Process Monitor Info") or []:
        if isinstance(item, dict):
            out.append(entries_to_dict(item.get("e")))
    return out


def fmt_ts(ts_ms: int | None) -> str:
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S") if ts_ms else "?"


def report(pm: dict, name_filter: str, history: dict[int, list[tuple[str, object]]]) -> None:
    ts = snapshot_ts_ms(pm)
    procs = processes(pm)
    stamp = fmt_ts(ts)
    values = [p.get("IsActive") for p in procs]
    fields = sorted({k for p in procs for k in p if k is not None})
    print(f"\n[{stamp}] {len(procs)} processes | fields: {', '.join(fields)}")
    if values.count(None) == len(values):
        print("  IsActive: not reported by this agent for any process")
    else:
        print(f"  IsActive: true={values.count(True)} false={values.count(False)} missing={values.count(None)}")

    matches = [p for p in procs if name_filter.lower() in str(p.get("Name", "")).lower()]
    if not matches:
        print(f"  (no process matching '{name_filter}')")
    for p in matches:
        print(f"  MATCH {json.dumps(p, ensure_ascii=False)}")
        pid = p.get("PID")
        if isinstance(pid, (int, float)):
            history.setdefault(int(pid), []).append((stamp, p.get("IsActive")))

    # Only list processes reported as explicitly not active; a missing field is summarized above.
    inactive = [p for p in procs if p.get("IsActive") is False and p not in matches]
    if inactive:
        names = ", ".join(f"{p.get('Name')}({p.get('PID')})={p.get('IsActive')}" for p in inactive[:30])
        more = f" ... +{len(inactive) - 30}" if len(inactive) > 30 else ""
        print(f"  IsActive=false: {names}{more}")


def summarize(history: dict[int, list[tuple[str, object]]], name_filter: str) -> None:
    print("\n=== IsActive timeline of matching processes ===")
    if not history:
        print(f"no process matching '{name_filter}' was seen")
        return
    for pid, points in history.items():
        changes = [points[0]] + [pt for prev, pt in zip(points, points[1:]) if pt[1] != prev[1]]
        print(f"PID {pid}: " + " -> ".join(f"{v} @{t}" for t, v in changes) + f"  ({len(points)} snapshots)")


async def main() -> None:
    args = parse_args()
    client = DeviceOnClient(Settings.from_env())
    history: dict[int, list[tuple[str, object]]] = {}
    try:
        dev = await resolve_device(client, args.did, args.device)
        print(f"device {dev.get('name')} did={dev.get('did')} agentId={dev.get('agentId')} connected={dev.get('connected')}")
        if not dev.get("connected"):
            raise SystemExit("device is offline; the agent must be connected to upload process data")

        did, agent_id = dev["did"], dev["agentId"]
        first = await client.get_latest_data(did, agent_id, PLUGIN)
        last_ts = snapshot_ts_ms((first or {}).get(PLUGIN) or {})  # ignore anything uploaded before we started

        start = time.monotonic()
        renewed_at = -RENEW_EVERY_SEC
        while (elapsed := time.monotonic() - start) < args.duration:
            if elapsed - renewed_at >= RENEW_EVERY_SEC:
                resp = await client.start_intermittent_report(agent_id, PLUGIN, args.interval, KEEP_ALIVE_SEC)
                if resp.get("result") is False:
                    print(f"warning: intermittent_report refused: {resp}")
                renewed_at = elapsed

            pm = ((await client.get_latest_data(did, agent_id, PLUGIN)) or {}).get(PLUGIN) or {}
            ts = snapshot_ts_ms(pm)
            if ts is not None and (last_ts is None or ts > last_ts) and pm.get("Process Monitor Info"):
                last_ts = ts
                report(pm, args.name, history)
                if args.jsonl:
                    with open(args.jsonl, "a", encoding="utf-8") as f:
                        f.write(json.dumps(pm, ensure_ascii=False) + "\n")
            await asyncio.sleep(min(2, args.interval))
    except DeviceOnError as ex:
        raise SystemExit(f"DeviceOn API error: {ex}") from ex
    except KeyboardInterrupt:
        pass
    finally:
        summarize(history, args.name)
        await client.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
