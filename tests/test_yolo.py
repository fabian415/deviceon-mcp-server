"""YOLO mode (DEVICEON_AUTO_CONFIRM): request_* executes immediately for the listed actions."""

from dataclasses import replace

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from deviceon_mcp import actions
from deviceon_mcp.tools import register_toolsets
from deviceon_mcp.tools.control import kill
from deviceon_mcp.tools.remote import command

from fake_deviceon import DID, STRESS_NAME, STRESS_PID


def _yolo(deps, *names, remote=True):
    deps.settings = replace(deps.settings, auto_confirm=frozenset(names), allow_remote_command=remote)
    mcp = FastMCP("t")
    register_toolsets(mcp, deps, ("control", "remote") if remote else ("control",))
    return mcp


async def test_auto_confirmed_command_runs_without_token(deps):
    _yolo(deps, "run_command")
    r = await command.request_run_command(deps, DID, "hostname")
    assert r["auto_confirmed"] is True and "confirm_token" not in r
    assert r["status"] == "completed" and "hostname" in deps.terminal.calls[0]


async def test_risky_script_still_needs_confirmation(deps):
    _yolo(deps, "run_command")
    r = await command.request_run_command(deps, DID, "Stop-Service Spooler")
    assert r["confirm_token"] and "auto_confirm_skipped" in r
    assert deps.terminal.calls == []


async def test_actions_not_listed_keep_two_steps(deps, fake):
    _yolo(deps, "run_command")
    r = await kill.request_kill_process(deps, DID, STRESS_PID, STRESS_NAME)
    assert r["confirm_token"] and "auto_confirm_skipped" not in r
    assert fake.killed == []


async def test_all_auto_kills_but_safety_checks_still_apply(deps, fake):
    _yolo(deps, "all")
    with pytest.raises(ToolError, match="protected"):
        await kill.request_kill_process(deps, DID, 100, "cagent")
    r = await kill.request_kill_process(deps, DID, STRESS_PID, STRESS_NAME)
    assert r["auto_confirmed"] is True and r["status"] == "killed"
    assert fake.killed == [STRESS_PID]


def test_unknown_action_name_is_rejected(deps):
    with pytest.raises(RuntimeError, match="DEVICEON_AUTO_CONFIRM"):
        _yolo(deps, "run_comand")


def test_action_of_disabled_toolset_is_rejected(deps):
    with pytest.raises(RuntimeError, match="run_command"):
        _yolo(deps, "run_command", remote=False)  # action exists only when 'remote' is enabled


async def test_annotations_reflect_auto_confirm(deps):
    mcp = _yolo(deps, "run_command")
    tools = {t.name: t for t in await mcp.list_tools()}
    assert tools["request_run_command"].annotations.readOnlyHint is False
    assert tools["request_run_command"].annotations.destructiveHint is True
    assert tools["request_kill_process"].annotations.readOnlyHint is True


def test_off_by_default(deps):
    assert deps.settings.auto_confirm == frozenset()
    assert not actions.is_auto_confirmed(deps, "kill_process")
