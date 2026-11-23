"""Wake a shut-down device through a neighbouring device (DeviceOn Wake-on-LAN "agent mode").

How DeviceOn does it (Worker DeviceControl.wakeOnLan, verified in the backend source):
PUT /power/device action=start becomes commCmd 999, which the Worker intercepts. Every 10 s for
10 minutes, until the device reconnects, it sends the magic packet according to the device's
wolmode: 1 = the server broadcasts it itself, 2 = it asks the online agent named in wolrepeater
(commCmd 85 + the target's MACs) to broadcast it on its own LAN, 3 = it sends it to the IP in
wolrepeater. With wolmode 0, or an offline relay agent, it silently does nothing and only reports
failure after the 10 minutes, so request_power_action checks this up front.

A relay must share the target's broadcast domain. DeviceOn does not store netmasks and real
subnets are not always /24 (172.22.12.255 and 172.22.13.77 share a /23 on the test LAN), so
find_wol_relay_candidates asks each candidate for its own IPv4 prefixes over the terminal.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp.exceptions import ToolError

from ...actions import issue_action
from ...client import DeviceOnError
from ...deps import Deps
from ...remote_exec import RemoteExecError, as_list, is_windows, run_json_probe
from ..common.devices import WOL_MODES, device_ref, get_device_checked, plugin_names
from ..common.devices import agent_id as agent_id_of

ACTION_CONFIG = "wol_config"
MODE_CODES = {"off": 0, "direct": 1, "agent": 2, "repeater": 3}
WORKER_RETRY_SEC = 600   # the Worker resends for 10 minutes
_MAC = re.compile(r"^[0-9A-Fa-f]{12}$")


def ipv4(value: object) -> ipaddress.IPv4Address | None:
    try:
        return ipaddress.IPv4Address(str(value or "").strip())
    except ValueError:
        return None


def common_prefix_bits(a: ipaddress.IPv4Address, b: ipaddress.IPv4Address) -> int:
    return 32 - (int(a) ^ int(b)).bit_length()


def _iso(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None


async def device_by_agent_id(deps: Deps, agent_id: str) -> dict | None:
    if not agent_id:
        return None
    data = await deps.client.list_devices(like=agent_id, like_field="agentId", page_size=5)
    for d in (data or {}).get("devices") or []:
        if str(agent_id_of(d) or "").lower() == agent_id.lower():
            return d
    return None


def _relay_ref(d: dict) -> dict:
    return {"did": d.get("did"), "name": d.get("name"), "online": bool(d.get("connected")), "localIp": d.get("localip")}


async def wol_status(deps: Deps, dev: dict) -> dict:
    """Current Wake-on-LAN config of a device and whether a wake-up could work right now."""
    mode = int(dev.get("wolmode") or 0)
    rep = str(dev.get("wolrepeater") or "")
    out: dict = {"mode": WOL_MODES.get(mode, str(mode)), "ready": False}
    if mode == 0:
        out["problem"] = ("Wake-on-LAN is not configured (wolmode=0): DeviceOn would send nothing. "
                          "Use find_wol_relay_candidates, then request_configure_wol.")
    elif mode == 1:
        out.update(ready=True, note="the DeviceOn server broadcasts the magic packet itself; this only works when "
                                    "the server is on the device's LAN (rare for a cloud server). Agent mode is safer.")
    elif mode == 2:
        try:
            relay = await device_by_agent_id(deps, rep)
        except DeviceOnError as ex:
            relay, out["problem"] = None, f"could not look up the relay agent: {ex}"
        if relay:
            out["relay"] = _relay_ref(relay)
            out["ready"] = bool(relay.get("connected"))
            if not out["ready"]:
                out["problem"] = (f"relay device {relay.get('name')} is offline; DeviceOn would send nothing. "
                                  "Pick another relay with find_wol_relay_candidates.")
        elif "problem" not in out:
            out["problem"] = f"relay agent {rep!r} no longer exists in DeviceOn."
    elif mode == 3:
        out.update(ready=True, relay_ip=rep,
                   note="the server sends the packet to this IP; it must forward it as a broadcast on the device's LAN.")
    return out


async def last_seen_ms(deps: Deps, dev: dict) -> int | None:
    """Timestamp of the device's newest stored CPU sample (≈ when it went offline).

    No plugin check: an offline device reports no plugins, yet its stored history is still readable.
    """
    end = datetime.fromtimestamp(deps.now_ms() / 1000, timezone.utc)
    try:
        items = await deps.client.get_hist_data(dev["did"], agent_id_of(dev), "ProcessMonitor",
                                                "/System Monitor Info/CPU Usage", end - timedelta(days=7), end,
                                                amount=1, order="desc")
    except DeviceOnError:
        return None
    ts = [int(i["ts"]) for i in items if isinstance(i.get("ts"), (int, float))]
    return max(ts) if ts else None


def _probe_script(target_mac: str | None) -> str:
    lines = [
        "#DOMCP:subnet",
        "$a=@(Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | ?{ $_.IPAddress -notlike '127.*' -and "
        "$_.IPAddress -notlike '169.254.*' } | %{ [pscustomobject]@{ip=$_.IPAddress;prefix=[int]$_.PrefixLength;nic=$_.InterfaceAlias} })",
        "$n=@()",
    ]
    if target_mac:
        mac = "-".join(target_mac[i:i + 2] for i in range(0, 12, 2)).upper()
        lines.append(f"$n=@(Get-NetNeighbor -LinkLayerAddress '{mac}' -EA SilentlyContinue | %{{ $_.IPAddress }})")
    lines.append("$r=@{addrs=$a;neighbor=$n}")
    return "\n".join(lines)


async def probe_relay(deps: Deps, relay: dict, target_ip: ipaddress.IPv4Address | None, target_mac: str | None) -> dict:
    """Ask a (Windows, online) candidate for its IPv4 networks; is the target's last IP inside one?"""
    mac = target_mac if target_mac and _MAC.match(target_mac) else None
    try:
        data = await run_json_probe(deps, relay, _probe_script(mac), 45) or {}
    except RemoteExecError as ex:
        return {"same_subnet": None, "probe_error": str(ex)}
    nets = []
    for a in as_list(data.get("addrs")):
        try:
            nets.append((ipaddress.IPv4Interface(f"{a['ip']}/{int(a['prefix'])}").network, a.get("nic")))
        except (KeyError, ValueError, TypeError):
            continue
    hits = [str(n) for n, _ in nets if target_ip and target_ip in n]
    out = {"networks": [f"{n} ({nic})" for n, nic in nets], "same_subnet": bool(hits) if target_ip else None}
    if hits:
        out["shared_subnet"] = hits[0]
    if mac:
        out["sees_target_mac"] = bool(as_list(data.get("neighbor")))  # target in the candidate's ARP cache
    return out


def _can_probe(d: dict) -> bool:
    return bool(d.get("connected")) and is_windows(d) and "terminal" in plugin_names(d)


async def find_wol_relay_candidates(deps: Deps, did: int, verify: bool = True, max_verify: int = 5) -> dict:
    target = await get_device_checked(deps, did)
    tip = ipv4(target.get("localip"))
    mac = str(target.get("mac") or "")
    try:
        data = await deps.client.list_devices(connected=True, page_size=100)
    except DeviceOnError as ex:
        raise ToolError(f"cannot list online devices: {ex}") from ex
    rows = []
    for d in (data or {}).get("devices") or []:
        if d.get("did") == did:
            continue
        ip = ipv4(d.get("localip"))
        row = {**_relay_ref(d), "os": d.get("ostype"),
               "common_prefix_bits": common_prefix_bits(tip, ip) if tip and ip else None, "_dev": d}
        rows.append(row)
    rows.sort(key=lambda r: -(r["common_prefix_bits"] if r["common_prefix_bits"] is not None else -1))

    max_verify = max(0, min(max_verify, 10))
    probed = 0
    for r in rows:
        d = r.pop("_dev")
        if verify and probed < max_verify and (r["common_prefix_bits"] or 0) >= 16 and _can_probe(d):
            probed += 1
            r.update(await probe_relay(deps, d, tip, mac))
        else:
            r["same_subnet"] = None
            if verify and not _can_probe(d):
                r["not_verified"] = "needs an online Windows device with the terminal plugin"
    current = await wol_status(deps, target)
    recommended = next((r for r in rows if r.get("same_subnet")), None)
    cur_relay = (current.get("relay") or {}).get("did")
    if cur_relay is not None:
        for r in rows:
            r["is_current_relay"] = r["did"] == cur_relay

    if recommended and cur_relay == recommended["did"] and current["ready"]:
        hint = (f"The current relay {recommended['name']} is online and on the same subnet: no change needed. "
                "Next: request_power_action(action='start').")
    elif recommended:
        hint = (f"Ask the user whether to use {recommended['name']} (did {recommended['did']}) as the relay; if yes, call "
                f"request_configure_wol(did={did}, mode='agent', relay_did={recommended['did']}) and confirm_action, "
                "then request_power_action(action='start').")
    else:
        hint = ("No online device was verified to share the target's subnet. A relay on a different subnet cannot "
                "wake it (broadcasts do not cross routers). Pick one by IP closeness only if the user knows the "
                "network layout, or power the device on by hand.")
    return {
        "target": {**device_ref(target), "last_ip": target.get("localip"), "mac": mac or None,
                   "last_seen": _iso(await last_seen_ms(deps, target)), "wake_on_lan": current},
        "candidates": rows[:10],
        "recommended": recommended and {k: recommended[k] for k in ("did", "name", "localIp") if k in recommended},
        "next_step": hint,
        "note": "The target's IP is the last one DeviceOn saw. Wake-on-LAN also needs WOL enabled in the target's "
                "BIOS/NIC and a wired connection; DeviceOn cannot check that.",
    }


async def request_configure_wol(deps: Deps, did: int, mode: str, relay_did: int | None = None,
                                relay_ip: str | None = None, reason: str = "") -> dict:
    if mode not in MODE_CODES:
        raise ToolError(f"mode must be one of {', '.join(MODE_CODES)}")
    target = await get_device_checked(deps, did)
    warnings: list[str] = []
    new: dict = {"mode": mode}
    repeater = ""
    if mode == "agent":
        if relay_did is None:
            raise ToolError("mode='agent' needs relay_did (an online device on the same subnet; see find_wol_relay_candidates)")
        if relay_did == did:
            raise ToolError("a device cannot be its own Wake-on-LAN relay")
        relay = await get_device_checked(deps, relay_did)
        repeater = relay["agentId"]
        new["relay"] = _relay_ref(relay)
        if not relay.get("connected"):
            warnings.append(f"relay {relay.get('name')} is offline now; waking only works while it is online.")
        tip, rip = ipv4(target.get("localip")), ipv4(relay.get("localip"))
        if _can_probe(relay):
            probe = await probe_relay(deps, relay, tip, str(target.get("mac") or ""))
            new["relay_check"] = probe
            if probe.get("same_subnet") is False:
                warnings.append(f"{relay.get('name')} is NOT on the target's subnet ({', '.join(probe.get('networks') or [])}); "
                                "its broadcast will not reach the target.")
        elif tip and rip and common_prefix_bits(tip, rip) < 16:
            warnings.append(f"relay IP {rip} looks far from the target's last IP {tip}; it may be on another network.")
    elif mode == "repeater":
        if not ipv4(relay_ip):
            raise ToolError("mode='repeater' needs relay_ip, an IPv4 address that forwards the packet to the device's LAN")
        repeater = str(ipv4(relay_ip))
        new["relay_ip"] = repeater
    elif mode == "direct":
        warnings.append("direct mode only works when the DeviceOn server itself is on the device's LAN.")
    else:
        warnings.append("the device can no longer be woken up remotely.")
    summary = {"device": device_ref(target), "current": await wol_status(deps, target), "new": new,
               "reason": reason or None}
    params = {"did": did, "wolmode": MODE_CODES[mode], "wolrepeater": repeater}
    return await issue_action(deps, ACTION_CONFIG, params, summary, warnings)


async def execute_config(deps: Deps, params: dict) -> dict:
    try:
        resp = await deps.client.set_wol(params["did"], params["wolmode"], params["wolrepeater"])
    except DeviceOnError as ex:
        raise ToolError(f"setting Wake-on-LAN failed: {ex}") from ex
    ok = resp.get("result") is not False
    return {"status": "configured" if ok else "rejected", "portal_response": resp,
            "next_step": "If the device is offline, call request_power_action(action='start') to wake it." if ok
            else "The portal rejected the change (EditDevice permission?); nothing was changed."}


async def wait_for_device_online(deps: Deps, did: int, timeout_sec: int = WORKER_RETRY_SEC, poll_sec: int = 15,
                                 progress=None) -> dict:
    timeout_sec = max(15, min(timeout_sec, 1800))
    poll_sec = max(5, min(poll_sec, 60))
    start = deps.now_ms()
    dev = await get_device_checked(deps, did)
    while not dev.get("connected"):
        waited = (deps.now_ms() - start) / 1000
        if waited >= timeout_sec:
            return {"device": device_ref(dev), "online": False, "waited_sec": round(waited),
                    "next_step": "The device did not come back. Check the relay is online and on the same subnet, "
                                 "that WOL is enabled in the device's BIOS/NIC, or power it on by hand."}
        if progress:
            await progress(waited, timeout_sec, f"waiting for {dev.get('name')} to reconnect")
        await deps.sleep(poll_sec)
        dev = await get_device_checked(deps, did)
    waited = round((deps.now_ms() - start) / 1000)
    return {"device": device_ref(dev), "online": True, "waited_sec": waited,
            "next_step": "Give the agent ~30 s to load its plugins, then call analyze_last_shutdown to find out why it "
                         "went down."}
