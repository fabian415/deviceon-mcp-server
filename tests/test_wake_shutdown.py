"""Scenario 4: find a relay, configure Wake-on-LAN, wake the device, explain the shutdown, disable the culprit."""

from datetime import datetime, timedelta, timezone

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from deviceon_mcp import actions
from deviceon_mcp.tools import control
from deviceon_mcp.tools.common import devices
from deviceon_mcp.tools.control import autostart as disable
from deviceon_mcp.tools.control import capabilities, power, wake
from deviceon_mcp.tools.diagnose import autostart
from deviceon_mcp.tools.logs import shutdown

from fake_deviceon import DID, RELAY_AGENT_ID, RELAY_DID


@pytest.fixture
def cdeps(deps):
    control.register(FastMCP("test"), deps)
    return deps


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---- finding the offline device and a relay --------------------------------

async def test_list_devices_offline_only_shows_wol_mode(deps, fake):
    fake.connected = False
    r = await devices.list_devices(deps, offline_only=True)
    assert [d["did"] for d in r["devices"]] == [DID]
    assert r["devices"][0]["wakeOnLan"] == {"mode": "agent", "relay": "Line-B-HMI-01"}
    with pytest.raises(ToolError):
        await devices.list_devices(deps, connected_only=True, offline_only=True)


async def test_relay_candidate_verified_by_its_own_prefix_not_by_slash24(cdeps, fake):
    fake.connected = False
    r = await wake.find_wol_relay_candidates(cdeps, DID)
    cand = r["candidates"][0]
    # 10.0.1.20 vs 10.0.0.31 differ in the third octet, but the relay's /23 contains the target
    assert cand["did"] == RELAY_DID and cand["common_prefix_bits"] == 23
    assert cand["same_subnet"] is True and cand["shared_subnet"] == "10.0.0.0/23"
    assert cand["sees_target_mac"] is True and cand["is_current_relay"] is True
    assert r["recommended"]["did"] == RELAY_DID
    assert "no change needed" in r["next_step"]
    assert r["target"]["wake_on_lan"]["ready"] is True
    assert r["target"]["last_seen"]  # newest stored CPU sample
    assert cdeps.terminal.agents == [RELAY_AGENT_ID]   # only the relay was probed, never the offline target


async def test_relay_on_other_subnet_is_not_recommended(cdeps, fake):
    cdeps.terminal.relay_addrs = [{"ip": "10.0.1.20", "prefix": 24, "nic": "Ethernet"}]
    cdeps.terminal.relay_neighbor = []
    fake.connected = False
    r = await wake.find_wol_relay_candidates(cdeps, DID)
    assert r["candidates"][0]["same_subnet"] is False
    assert r["recommended"] is None and "cannot wake" in r["next_step"]


# ---- configuring Wake-on-LAN -------------------------------------------------

async def test_configure_wol_is_two_step(cdeps, fake):
    fake.wolmode, fake.wolrepeater = 0, ""
    r = await wake.request_configure_wol(cdeps, DID, "agent", relay_did=RELAY_DID, reason="device shut down")
    assert fake.wol_calls == []
    assert r["summary"]["current"]["mode"] == "not_set"
    assert r["summary"]["new"]["relay"]["name"] == "Line-B-HMI-01"
    assert r["summary"]["new"]["relay_check"]["same_subnet"] is True and not r["warnings"]
    done = await actions.confirm_action(cdeps, r["confirm_token"])
    assert done["status"] == "configured"
    assert fake.wol_calls == [{"devices": [{"did": DID, "wolmode": 2, "wolrepeater": RELAY_AGENT_ID}]}]


async def test_configure_wol_validates(cdeps, fake):
    with pytest.raises(ToolError, match="relay_did"):
        await wake.request_configure_wol(cdeps, DID, "agent")
    with pytest.raises(ToolError, match="own"):
        await wake.request_configure_wol(cdeps, DID, "agent", relay_did=DID)
    with pytest.raises(ToolError, match="relay_ip"):
        await wake.request_configure_wol(cdeps, DID, "repeater", relay_ip="not-an-ip")
    cdeps.terminal.relay_addrs = [{"ip": "10.0.1.20", "prefix": 24, "nic": "Ethernet"}]
    r = await wake.request_configure_wol(cdeps, DID, "agent", relay_did=RELAY_DID)
    assert any("NOT on the target's subnet" in w for w in r["warnings"])


# ---- waking up -----------------------------------------------------------------

async def test_start_refused_when_wol_not_set_or_relay_offline(cdeps, fake):
    fake.connected = False
    fake.wolmode, fake.wolrepeater = 0, ""
    with pytest.raises(ToolError, match="not configured"):
        await power.request_power_action(cdeps, DID, "start")
    fake.wolmode, fake.wolrepeater = 2, RELAY_AGENT_ID
    fake.relay_connected = False
    with pytest.raises(ToolError, match="offline"):
        await power.request_power_action(cdeps, DID, "start")
    assert fake.power_calls == []


async def test_wake_then_wait_for_online(cdeps, fake):
    fake.connected = False
    r = await power.request_power_action(cdeps, DID, "start", "shut down by watchdog")
    assert r["summary"]["wake_via"]["name"] == "Line-B-HMI-01"
    done = await actions.confirm_action(cdeps, r["confirm_token"])
    assert fake.power_calls == [{"did": DID, "action": "start"}]
    assert "wait_for_device_online" in done["next_step"]
    fake.online_at = fake.now + 95_000
    w = await wake.wait_for_device_online(cdeps, DID, poll_sec=15)
    assert w["online"] is True and 90 <= w["waited_sec"] <= 120



async def test_start_on_offline_device_without_plugins(cdeps, fake):
    """Real DS054 case: offline, so DeviceOn lists no plugins (no power_onoff); WOL must still be offered."""
    fake.connected = False
    fake.power_functions = ""   # power API knows nothing either -> fall back to the record's functionList
    dev = await cdeps.client.get_device(DID)
    assert dev["plugins"] == []
    r = await power.request_power_action(cdeps, DID, "start")
    assert r["summary"]["power_action"] == "start"
    assert not any("power_onoff" in w for w in r["warnings"])
    caps = await capabilities.get_device_capabilities(cdeps, DID)
    assert caps["tools"]["request_power_action"]["usable_now"] == ["start"]
    assert caps["tools"]["wake_on_lan"]["ready"] is True
    assert any("reports no plugins" in n for n in caps["notes"])
    # online actions still need the plugin: offline + plugin-gated tool says "offline", not "install it"
    with pytest.raises(ToolError, match="is offline; its plugins"):
        await devices.get_device_checked(cdeps, DID, require_plugin="ProcessMonitor")

async def test_wait_for_online_times_out(cdeps, fake):
    fake.connected = False
    w = await wake.wait_for_device_online(cdeps, DID, timeout_sec=60, poll_sec=15)
    assert w["online"] is False and w["waited_sec"] >= 60


# ---- why did it go down ------------------------------------------------------------

def _ev(t, p, i, d=None, m="", log="System", lv=4):
    return {"t": iso(t), "p": p, "id": i, "d": d or {}, "m": m, "log": log, "lv": lv}


def _watchdog_shutdown(boot: datetime) -> list[dict]:
    down = boot - timedelta(minutes=20)
    return [
        _ev(down - timedelta(minutes=12), shutdown.RED, 2004,
            {"ProcessName": "pressure_leak.exe", "Id": "4321", "CommitCharge": "11811160064"},
            "Windows successfully diagnosed a low virtual memory condition. The following programs consumed the most "
            "virtual memory: pressure_leak.exe (4321) consumed 11811160064 bytes, chrome.exe (200) consumed 300000000 bytes"),
        _ev(down - timedelta(seconds=31), "DeviceOnSim", 3001, {},
            "MemGuard: memory load 93% >= 90% for 60 s. Top private memory: pressure_leak.exe(4321) 11264 MB, "
            "svchost.exe(900) 200 MB Initiating protective power-off in 30 s.", log="Application", lv=3),
        _ev(down - timedelta(seconds=30), shutdown.U32, 1074, {
            "param1": "C:\\ProgramData\\DeviceOnSim\\Shutdown\\mem_guard.exe (DS054-H5T3KU4)", "param2": "DS054-H5T3KU4",
            "param3": "應用程式: 不穩定 (未計劃)", "param4": "0x40006", "param5": "關閉電源",
            "param6": "MemGuard: memory load 93% ... Top private memory: pressure_leak.exe(4321) 11264 MB",
            "param7": "NT AUTHORITY\\SYSTEM"}),
        _ev(down - timedelta(seconds=2), shutdown.EL, 6006),
        _ev(down, shutdown.KG, 13),
        _ev(boot, shutdown.KG, 12),
        _ev(boot + timedelta(seconds=20), shutdown.EL, 6005),
    ]


def test_classify_watchdog_shutdown_points_at_the_leak_not_the_watchdog():
    boot = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
    c = shutdown.classify(_watchdog_shutdown(boot), boot)
    assert c["kind"] == "initiated"
    assert c["initiated_by"]["process"] == "mem_guard.exe"          # computer-name suffix stripped
    assert c["initiated_by"]["user"] == "NT AUTHORITY\\SYSTEM"
    assert c["shutdown_time"] == (boot - timedelta(minutes=20)).isoformat()
    assert c["suspects"][0]["process"] == "pressure_leak.exe"
    assert all(s["process"] not in ("mem_guard.exe", "svchost.exe") for s in c["suspects"])
    assert c["resource_exhaustion"]["events"] == 1
    assert [e["id"] for e in c["timeline"]][-2:] == [12, 6005]


@pytest.mark.parametrize("data,kind", [
    ({"BugcheckCode": "209", "PowerButtonTimestamp": "0"}, "bugcheck"),
    ({"BugcheckCode": "0", "PowerButtonTimestamp": "133781234567890123"}, "forced_power_button"),
    ({"BugcheckCode": "0", "PowerButtonTimestamp": "0"}, "unexpected"),
])
def test_classify_dirty_shutdowns(data, kind):
    boot = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
    events = [_ev(boot - timedelta(hours=1), "Application Error", 1000, {"param1": "hmi.exe"}, log="Application", lv=2),
              _ev(boot + timedelta(seconds=10), shutdown.KP, 41, data),
              _ev(boot + timedelta(seconds=15), shutdown.EL, 6008)]
    c = shutdown.classify(events, boot)
    assert c["kind"] == kind
    assert c["shutdown_time"] == (boot - timedelta(hours=1)).isoformat()  # last thing logged before it died
    if kind == "bugcheck":
        assert c["bugcheck_code"] == "0xD1"
    assert c["app_crashes_before"] == {"hmi.exe": 1}


def test_user_shutdown_from_start_menu_blames_nobody():
    """Shape captured from DS054-H5T3KU4 (2026-11-20): Start-menu shutdown plus agent-component crashes."""
    boot = datetime(2026, 11, 20, 5, 27, 35, tzinfo=timezone.utc)
    down = datetime(2026, 11, 20, 4, 35, 39, tzinfo=timezone.utc)
    crash = {"AppName": "WindowsFeature.exe", "AppVersion": "1.0.1.5", "ModuleName": "KERNELBASE.dll",
             "AppPath": "C:\\Program Files\\Advantech\\DeviceOn Agent\\WindowsFeature.exe"}
    events = [
        _ev(down - timedelta(minutes=9), "Application Error", 1000, {"AppName": "CAgent.exe", "ModuleName": "EmbDDC.dll"},
            "Faulting application name: CAgent.exe ...", log="Application", lv=2),
        _ev(down - timedelta(seconds=8), "Microsoft-Windows-RestartManager", 10010, {},
            "Application 'C:\\Program Files\\AMD\\CNext\\CNext\\RadeonSoftware.exe' (pid 5456) cannot be restarted",
            log="Application", lv=3),
        _ev(down - timedelta(seconds=10), shutdown.U32, 1074, {
            "param1": "C:\\Windows\\SystemApps\\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\\"
                      "StartMenuExperienceHost.exe (DESKTOP-H5T3KU4)",
            "param3": "Other (Unplanned)", "param4": "0x0", "param5": "power off", "param6": "",
            "param7": "DESKTOP-H5T3KU4\\ds-054"}),
        *[_ev(down - timedelta(seconds=7 - i), "Application Error", 1000, crash,
              "Faulting application name: WindowsFeature.exe, version: 1.0.1.5", log="Application", lv=2) for i in range(3)],
        _ev(down, shutdown.KG, 13),
        _ev(boot, shutdown.KG, 12),
    ]
    c = shutdown.classify(events, boot)
    assert c["kind"] == "initiated" and c["initiated_by"]["interactive"] is True
    assert c["suspects"] == []                      # crashes and RestartManager noise are not suspects
    assert c["app_crashes_before"] == {"WindowsFeature.exe": 3, "CAgent.exe": 1}
    assert c["app_events_before_shutdown"][-1]["repeated"] == 3
    findings, fixes = shutdown._advice(c, {"memory_rising_before_offline": False}, [
        {"name": "Radeonsoftware.exe", "pid": 5456, "private_mb": 282, "started": iso(boot + timedelta(seconds=40))}], boot)
    assert any("most likely deliberate" in f for f in findings)
    assert fixes == [] and not any("running again" in f for f in findings)


def test_classify_unknown_when_window_is_empty():
    boot = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
    assert shutdown.classify([], boot)["kind"] == "unknown"


async def test_analyze_last_shutdown_end_to_end(cdeps, fake):
    boot = datetime.fromtimestamp(fake.now / 1000, timezone.utc) - timedelta(minutes=5)
    down = boot - timedelta(minutes=20)
    fake.scenario_pressure_until = int(down.timestamp() * 1000)
    cdeps.terminal.shutdown_probe = {
        "now": iso(boot + timedelta(minutes=5)), "boot": iso(boot), "ev": _watchdog_shutdown(boot), "err": [],
        "top": [{"name": "pressure_leak.exe", "pid": 777, "private_mb": 900, "started": iso(boot + timedelta(minutes=2)),
                 "path": "C:\\ProgramData\\DeviceOnSim\\Shutdown\\pressure_leak.exe"},
                {"name": "cagent.exe", "pid": 50, "private_mb": 80, "started": iso(boot), "path": None}],
        "mem_total_mb": 15621, "mem_free_mb": 9000, "commit_limit_mb": 18000, "commit_free_mb": 9500,
    }
    r = await shutdown.analyze_last_shutdown(cdeps, DID)
    assert r["previous_shutdown"]["kind"] == "initiated" and r["uptime_min"] == 5
    hist = r["deviceon_history_before_offline"]
    assert hist["memory_rising_before_offline"] is True
    assert hist["memory_pct"]["last"] >= 90 and hist["memory_pct"]["min"] <= 50
    text = " ".join(r["findings"])
    assert "only pressed the button" in text and "Already running again" in text and "pressure_leak.exe" in text
    fixes = " ".join(r["suggested_fixes"])
    assert "request_kill_process" in fixes and "find_process_autostart(names=['pressure_leak.exe'])" in fixes


async def test_analyze_last_shutdown_needs_online_device(cdeps, fake):
    fake.connected = False
    with pytest.raises(ToolError, match="offline"):
        await shutdown.analyze_last_shutdown(cdeps, DID)


def test_shutdown_probe_fits_terminal_limit():
    from deviceon_mcp.remote_exec import JSON_EMIT, MAX_CMDLINE, encode_ps
    assert len(encode_ps(shutdown.probe_script(168) + "\n" + JSON_EMIT)) < MAX_CMDLINE
    assert len(encode_ps(autostart.probe_script(["a" * 64] * 5) + "\n" + JSON_EMIT)) < MAX_CMDLINE


# ---- what starts it, and turning that off ---------------------------------------------

async def test_find_process_autostart(cdeps, fake):
    cdeps.terminal.autostart_result = {
        "tasks": {"path": "\\DeviceOnSim\\PressureLeak", "state": "Running", "user": "SYSTEM",
                  "run": "C:\\ProgramData\\DeviceOnSim\\Shutdown\\pressure_leak.exe --rate 256", "triggers": "Boot"},
        "services": None, "run_keys": None, "startup_files": None,
        "running": {"name": "pressure_leak.exe", "pid": 777, "parent": "svchost.exe (1200)"},
    }
    r = await autostart.find_process_autostart(cdeps, DID, ["pressure_leak.exe"])
    assert r["tasks"][0]["path"] == "\\DeviceOnSim\\PressureLeak"   # single object unwrapped to a list
    assert r["services"] == []
    assert "kind='scheduled_task', name='\\DeviceOnSim\\PressureLeak'" in r["next_step"][0]
    script = cdeps.terminal.calls[-1]
    assert "$names=@('pressure_leak')" in script
    with pytest.raises(ToolError, match="invalid program name"):
        await autostart.find_process_autostart(cdeps, DID, ["x; Remove-Item C:\\"])


async def test_disable_autostart_two_step(cdeps, fake):
    cdeps.terminal.task_state = {"exists": True, "state": "Running", "user": "SYSTEM",
                                 "run": "C:\\ProgramData\\DeviceOnSim\\Shutdown\\pressure_leak.exe --rate 256",
                                 "exe": ["C:\\ProgramData\\DeviceOnSim\\Shutdown\\pressure_leak.exe"]}
    r = await disable.request_disable_autostart(cdeps, DID, "scheduled_task", "\\DeviceOnSim\\PressureLeak",
                                                reason="leak causes protective shutdowns")
    assert cdeps.terminal.disabled == []
    assert r["summary"]["undo"] == "Enable-ScheduledTask -TaskPath '\\DeviceOnSim\\' -TaskName 'PressureLeak'"
    assert any("SYSTEM" in w for w in r["warnings"])
    done = await actions.confirm_action(cdeps, r["confirm_token"])
    assert done["status"] == "disabled"
    script = cdeps.terminal.disabled[0]
    assert "Stop-ScheduledTask -TaskPath '\\DeviceOnSim\\' -TaskName 'PressureLeak'" in script
    assert "Disable-ScheduledTask" in script


async def test_disable_autostart_refusals(cdeps, fake):
    with pytest.raises(ToolError, match="full task path"):
        await disable.request_disable_autostart(cdeps, DID, "scheduled_task", "PressureLeak'; rm -r C:\\")
    cdeps.terminal.task_state = {"exists": False}
    with pytest.raises(ToolError, match="does not exist"):
        await disable.request_disable_autostart(cdeps, DID, "scheduled_task", "\\Vendor\\Gone")
    cdeps.terminal.task_state = {"exists": True, "state": "Ready", "run": "C:\\Windows\\system32\\defrag.exe"}
    with pytest.raises(ToolError, match="built-in Windows task"):
        await disable.request_disable_autostart(cdeps, DID, "scheduled_task", "\\Microsoft\\Windows\\Defrag\\ScheduledDefrag")
    cdeps.terminal.task_state = {"exists": True, "state": "Running", "start": "Auto",
                                 "path": "\"C:\\Program Files (x86)\\Advantech\\WISE-Agent\\cagent.exe\""}
    with pytest.raises(ToolError, match="DeviceOn/WISE agent"):
        await disable.request_disable_autostart(cdeps, DID, "service", "CAgent")
    cdeps.terminal.task_state = {"exists": True, "state": "Running", "start": "Auto",
                                 "path": "C:\\Windows\\system32\\svchost.exe -k netsvcs"}
    with pytest.raises(ToolError, match="svchost"):
        await disable.request_disable_autostart(cdeps, DID, "service", "Schedule")
    assert cdeps.terminal.disabled == []


async def test_list_devices_last_connected_and_recent_first(deps, fake):
    r = await devices.list_devices(deps, recent_first=True)
    names = [d["did"] for d in r["devices"]]
    assert names == [RELAY_DID, DID]   # relay logged in later
    assert all(d["lastConnectedAt"] for d in r["devices"])
    assert devices.ms_to_local_iso(None) is None
