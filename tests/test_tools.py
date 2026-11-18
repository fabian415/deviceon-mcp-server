"""End-to-end tests of the tool logic against the fake DeviceOn REST API."""

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from deviceon_mcp.tools.common.devices import list_devices
from deviceon_mcp.tools.diagnose import metrics, processes

from fake_deviceon import DID, STRESS_NAME, STRESS_PID


async def test_list_devices_filters_by_name(deps, fake):
    r = await list_devices(deps, filter="aoi-03")
    assert r["returned"] == 1
    d = r["devices"][0]
    assert d["did"] == DID and d["canDiagnoseProcesses"] is True and d["groups"] == ["Line-B"]
    assert (await list_devices(deps, filter="nope"))["returned"] == 0


async def test_list_devices_rejects_bad_field(deps):
    with pytest.raises(ToolError):
        await list_devices(deps, field="password")


async def test_analyze_detects_periodic_cpu(deps):
    r = await metrics.analyze_metric_periodicity(deps, DID, "cpu", 30)
    assert r["periodic"] is True, r
    assert abs(r["period_sec"] - 180) <= 5
    assert r["sensor"] == "ProcessMonitor:/System Monitor Info/CPU Usage"
    assert r["device"]["name"] == "Line-B-AOI-03"


async def test_analyze_temperature_resolves_susi_sensor(deps):
    plugin, sensor = await metrics.resolve_sensor(deps, {"did": DID, "agentId": "x", "plugins": []}, "SUSIControl:/Hardware Monitor/Temperature/CPU")
    assert (plugin, sensor) == ("SUSIControl", "/Hardware Monitor/Temperature/CPU")
    with pytest.raises(ToolError):
        await metrics.resolve_sensor(deps, {}, "bogus")


async def test_current_metrics_reads_cpu_memory_temperature(deps):
    r = await metrics.get_current_metrics(deps, DID)
    assert r["cpu_usage_pct"] is not None
    assert r["memory"]["used_pct"] == 75.0
    assert r["temperatures"]["plugin"] == "SUSIControl"
    assert "/Hardware Monitor/Temperature/CPU" in r["temperatures"]["readings_c"]


async def test_capture_finds_stress_process(deps):
    r = await processes.capture_top_processes(deps, DID, duration_sec=200, samples=21)
    assert r["system_cpu"]["spike_observed"] is True
    assert r["suspect"]["type"] == "process"
    assert r["suspect"]["pid"] == STRESS_PID
    assert r["top_processes"][0]["correlation"] > 0.9
    # chrome runs as two pids -> reported as a group, but not as the suspect
    assert any(g["name"] == "chrome" and g["instances"] == 2 for g in r["top_process_groups"])


async def test_capture_without_spike_names_no_suspect(deps, fake):
    fake.now += 120_000 - fake.now % 180_000  # move into a quiet phase
    r = await processes.capture_top_processes(deps, DID, duration_sec=30, samples=7)
    assert r["system_cpu"]["spike_observed"] is False
    assert r["suspect"] is None


async def test_capture_dedupes_cached_snapshots(deps):
    # 1 s apart but the server only refreshes every 5 s
    r = await processes.capture_top_processes(deps, DID, duration_sec=5, samples=6)
    assert r["unique_snapshots"] < 6


async def test_protected_process_is_refused(deps, fake):
    with pytest.raises(ToolError, match="protected"):
        await processes.request_kill_process(deps, DID, 1, "systemd")
    with pytest.raises(ToolError, match="protected"):
        await processes.request_kill_process(deps, DID, 100, "cagent")
    assert fake.killed == []


async def test_request_does_not_kill(deps, fake):
    r = await processes.request_kill_process(deps, DID, STRESS_PID, STRESS_NAME, "tracks spikes")
    assert r["confirm_token"] and r["summary"]["process"]["pid"] == STRESS_PID
    assert fake.killed == []
    assert not any(req.method == "PUT" and req.url.path == "/rmm/v1/processes" for req in fake.requests)


async def test_request_rejects_wrong_name(deps):
    with pytest.raises(ToolError, match="reused"):
        await processes.request_kill_process(deps, DID, STRESS_PID, "nginx")


async def test_full_kill_flow_and_token_is_single_use(deps, fake):
    token = (await processes.request_kill_process(deps, DID, STRESS_PID, STRESS_NAME))["confirm_token"]
    r = await processes.confirm_kill_process(deps, token)
    assert r["status"] == "killed" and r["killed"] is True
    assert fake.killed == [STRESS_PID]
    with pytest.raises(ToolError, match="unknown, already used, or expired"):
        await processes.confirm_kill_process(deps, token)

    # after the kill the periodic pattern is gone in fresh history
    fake.now += 30 * 60_000
    after = await metrics.analyze_metric_periodicity(deps, DID, "cpu", 20)
    assert after["periodic"] is False


async def test_confirm_aborts_when_pid_reused(deps, fake):
    token = (await processes.request_kill_process(deps, DID, STRESS_PID, STRESS_NAME))["confirm_token"]
    fake.stress_name = "postgres"  # same pid now belongs to another program
    fake.now += 10_000
    r = await processes.confirm_kill_process(deps, token)
    assert r["status"] == "aborted_pid_reused" and r["killed"] is False
    assert fake.killed == []


async def test_confirm_with_garbage_token(deps):
    with pytest.raises(ToolError):
        await processes.confirm_kill_process(deps, "not-a-token")


# ---- process-list delivery (intermittent report / live table) ---------------


async def test_capture_triggers_intermittent_report_with_integer_seconds(deps, fake):
    r = await processes.capture_top_processes(deps, DID, duration_sec=200, samples=21)
    assert r["process_list_available"] is True
    call = fake.intermittent_calls[0]
    assert call["plugin"] == "ProcessMonitor"
    assert isinstance(call["interval"], int) and 2 <= call["interval"] <= 10
    assert call["timeout"] >= 200  # stays alive for the whole capture


async def test_capture_reads_live_data_not_processes_endpoint(deps, fake):
    await processes.capture_top_processes(deps, DID, duration_sec=30, samples=7)
    paths = {req.url.path for req in fake.requests}
    assert f"/rmm/v1/processes/devices/{DID}" not in paths
    assert f"/rmm/v1/data/devices/{DID}/latestdata" in paths


async def test_capture_ignores_stale_live_snapshot(deps, fake):
    # Agent accepts the request but never uploads: only the 3-hour-old leftover
    # (which does contain a process list) is available. It must not be used.
    fake.agent_ignores_live = True
    r = await processes.capture_top_processes(deps, DID, duration_sec=30, samples=7)
    assert r["process_list_available"] is False
    assert r["suspect"] is None
    assert "no fresh process list" in r["notes"][0]


async def test_capture_reports_permission_problem(deps, fake):
    fake.fail_intermittent = True
    r = await processes.capture_top_processes(deps, DID, duration_sec=30, samples=7)
    assert r["process_list_available"] is False
    assert r["intermittent_report"]["requested"] is False
    assert "GetSensor" in r["notes"][0]


async def test_capture_on_offline_device_fails_clearly(deps, fake):
    fake.connected = False
    with pytest.raises(ToolError, match="offline"):
        await processes.capture_top_processes(deps, DID)


async def test_request_kill_uses_fresh_list(deps, fake):
    # The stale leftover lists the stress pid too; request must still trigger a live report.
    await processes.request_kill_process(deps, DID, STRESS_PID, STRESS_NAME)
    assert len(fake.intermittent_calls) == 1


async def test_confirm_aborts_without_fresh_data(deps, fake):
    token = (await processes.request_kill_process(deps, DID, STRESS_PID, STRESS_NAME))["confirm_token"]
    fake.now += 3600_000          # live report long expired
    fake.agent_ignores_live = True  # and the agent stops answering
    r = await processes.confirm_kill_process(deps, token)
    assert r["status"] == "aborted_no_fresh_data" and r["killed"] is False
    assert fake.killed == []


async def test_confirm_unverified_when_process_survives(deps, fake):
    fake.ignore_kill = True
    token = (await processes.request_kill_process(deps, DID, STRESS_PID, STRESS_NAME))["confirm_token"]
    r = await processes.confirm_kill_process(deps, token, verify_timeout_sec=10)
    assert r["status"] == "kill_sent_unverified" and r["killed"] is False


async def test_current_metrics_uses_periodic_copy(deps, fake):
    await metrics.get_current_metrics(deps, DID)
    pm_reads = [req for req in fake.requests
                if req.url.path.endswith("/latestdata") and "plugin=ProcessMonitor" in str(req.url)]
    assert pm_reads and all("source=autoreport" in str(req.url) for req in pm_reads)
