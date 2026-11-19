"""Tests of remote execution: terminal parsing, script review, run_command, logs, unresponsive windows."""

import base64
import json
from dataclasses import replace

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from deviceon_mcp import actions, remote_exec
from deviceon_mcp.terminal import clean_output, marker_regex
from deviceon_mcp.tools import remote
from deviceon_mcp.tools.diagnose import windows
from deviceon_mcp.tools.logs import eventlog
from deviceon_mcp.tools.remote import command

from fake_deviceon import DID


@pytest.fixture
def rdeps(deps):
    deps.settings = replace(deps.settings, allow_remote_command=True)
    remote.register(FastMCP("test"), deps)
    return deps


# ---- terminal output parsing (shapes captured from the real agent) ---------

M = "__DOMCP_END_abc__"
RAW = ("Microsoft Windows [Version 10.0.19045.6456]\r\n(c) Microsoft Corporation. All rights reserved.\r\n\r\n"
       f"C:\\Windows\\system32>whoami & echo {M}\r\nnt authority\\system\r\n{M}\r\n\r\nC:\\Windows\\system32>")


def test_clean_output_drops_banner_echo_marker_and_prompt():
    assert clean_output(RAW, f"whoami & echo {M}", M) == "nt authority\\system"


def test_marker_detected_after_clixml_without_newline_but_not_in_echo():
    rx = marker_regex(M)
    assert not rx.search(f"C:\\>cmd & echo {M}\n")
    raw = f"C:\\>x & echo {M}\nout\n<Objs Version=\"1.1.0.1\"><Obj/></Objs>{M}\n\nC:\\>"
    assert rx.search(raw)
    assert clean_output(raw, f"x & echo {M}", M) == "out"


# ---- script review ----------------------------------------------------------

def test_review_refuses_encoded_and_flags_risky_scripts():
    refusals, _ = remote_exec.review_script("powershell -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBi", frozenset())
    assert refusals
    _, warnings = remote_exec.review_script("Stop-Service Spooler; taskkill /im cagent.exe /f", frozenset({"cagent.exe"}))
    text = " ".join(warnings)
    assert "services" in text and "kills processes" in text and "cagent.exe" in text
    assert remote_exec.review_script("Get-Service | Where Status -eq Stopped", frozenset()) == ([], [])


# ---- run_command --------------------------------------------------------------

async def test_remote_toolset_needs_second_switch(deps):
    with pytest.raises(RuntimeError, match="DEVICEON_ALLOW_REMOTE_COMMAND"):
        remote.register(FastMCP("t"), deps)


async def test_run_command_system_shows_script_and_runs_only_after_confirm(rdeps):
    r = await command.request_run_command(rdeps, DID, "hostname\n'中文'", reason="check")
    assert r["summary"]["script"] == "hostname\n'中文'" and "SYSTEM" in r["summary"]["run_as"]
    assert rdeps.terminal.calls == []
    done = await actions.confirm_action(rdeps, r["confirm_token"])
    assert done["status"] == "completed" and done["output"] == "DESKTOP-TEST\r\n中文"
    assert "hostname" in rdeps.terminal.calls[0]


async def test_run_command_user_stages_launches_and_reads_event(rdeps, fake):
    r = await command.request_run_command(rdeps, DID, "Get-Process hang_app | Select Id,Responding", run_as="user")
    done = await actions.confirm_action(rdeps, r["confirm_token"])
    assert done["status"] == "completed" and done["output"] == rdeps.terminal.user_output
    (run_id, content), = rdeps.terminal.staged.items()
    assert "Get-Process hang_app" in content and f"DEVICEON-MCP {run_id}" in content and "LogEvent(4" in content
    launch = fake.launches[0]
    assert f"-File C:\\ProgramData\\DeviceOnMCP\\{run_id}.ps1" in launch["arg"] and len(launch["arg"]) <= 260


async def test_run_command_user_reports_launch_failure(rdeps, fake):
    fake.launch_result = False
    r = await command.request_run_command(rdeps, DID, "whoami", run_as="user")
    done = await actions.confirm_action(rdeps, r["confirm_token"])
    assert done["status"] == "launch_failed"
    assert any(c.startswith("del ") for c in rdeps.terminal.calls)  # staged script cleaned up


async def test_run_command_validation(rdeps, fake):
    with pytest.raises(ToolError, match="single line"):
        await command.request_run_command(rdeps, DID, "dir\nver", shell="cmd")
    with pytest.raises(ToolError, match="powershell"):
        await command.request_run_command(rdeps, DID, "whoami", shell="cmd", run_as="user")
    with pytest.raises(ToolError, match="limit"):
        await command.request_run_command(rdeps, DID, "x" * (remote_exec.MAX_SCRIPT + 1))
    with pytest.raises(ToolError, match="refused"):
        await command.request_run_command(rdeps, DID, "powershell -EncodedCommand SQBFAFgAIAAoAE4AZQB3AC0ATwBi")
    fake.ostype = "Ubuntu 22.04"
    with pytest.raises(ToolError, match="sh"):
        await command.request_run_command(rdeps, DID, "uname -a")
    r = await command.request_run_command(rdeps, DID, "uname -a", shell="sh")
    assert r["summary"]["shell"] == "sh"


async def test_terminal_failure_becomes_tool_error(rdeps):
    r = await command.request_run_command(rdeps, DID, "whoami")
    rdeps.terminal.fail = True
    with pytest.raises(ToolError, match="terminal connection failed"):
        await actions.confirm_action(rdeps, r["confirm_token"])


# ---- fetch_device_log -----------------------------------------------------------

async def test_fetch_log_via_terminal_parses_events(deps):
    r = await eventlog.fetch_device_log(deps, DID, "System", 60, "error", contains="service", max_events=10)
    assert r["matched"] == 1 and r["events"][0]["id"] == 7031  # single event unwrapped by PowerShell
    script = deps.terminal.calls[0]
    assert "LogName='System'" in script and "$f.Level = 1..2" in script and "IndexOf('service'" in script


async def test_fetch_log_escapes_quotes_and_rejects_bad_names(deps):
    await eventlog.fetch_device_log(deps, DID, "Application", contains="it's")
    assert "IndexOf('it''s'" in deps.terminal.calls[0]
    with pytest.raises(ToolError, match="invalid log name"):
        await eventlog.fetch_device_log(deps, DID, "System'; Remove-Item C:\\ -Recurse; '")


async def test_fetch_log_device_error(deps):
    deps.terminal.eventlog_error = "The specified channel could not be found."
    with pytest.raises(ToolError, match="channel could not be found"):
        await eventlog.fetch_device_log(deps, DID, "NoSuchLog")


async def test_fetch_log_devlog_reports_storage_failure(deps, fake):
    fake.devlog_error = "500:Copyfile fail : Syntax or usage error (&d)"
    with pytest.raises(ToolError, match="remote-storage"):
        await eventlog.fetch_device_log(deps, DID, "Application", source="devlog")
    fake.devlog_error = ""
    r = await eventlog.fetch_device_log(deps, DID, "Application", source="devlog")
    assert r["lines"] == ["line one", "line two"]


# ---- find_unresponsive_windows ----------------------------------------------------

def _windows_output(rows) -> str:
    return "J:" + base64.b64encode(json.dumps(rows).encode()).decode()


async def test_unresponsive_windows_separates_hung_from_suspended(deps):
    deps.terminal.user_output = _windows_output([
        {"pid": 4804, "name": "hang_app.exe", "responding": False, "suspended": False, "title": "hang_app"},
        {"pid": 9828, "name": "SystemSettings.exe", "responding": False, "suspended": True, "title": "Settings"},
        {"pid": 5020, "name": "explorer.exe", "responding": True, "suspended": False, "title": ""},
    ])
    r = await windows.find_unresponsive_windows(deps, DID)
    assert [w["pid"] for w in r["not_responding"]] == [4804]
    assert [w["pid"] for w in r["suspended_by_windows"]] == [9828]
    assert "request_kill_process" in r["next_step_hint"]


async def test_unresponsive_windows_none_found(deps):
    deps.terminal.user_output = _windows_output({"pid": 1, "name": "explorer.exe", "responding": True, "suspended": False})
    r = await windows.find_unresponsive_windows(deps, DID)
    assert r["not_responding"] == [] and "next_step_hint" not in r
