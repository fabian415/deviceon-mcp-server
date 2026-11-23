"""MCP-level checks: toolset registration, schemas, annotations, and a call through FastMCP."""

import json

from mcp.server.fastmcp import FastMCP

from deviceon_mcp.tools import register_toolsets

ALL = {
    "list_devices", "analyze_metric_periodicity", "get_current_metrics",
    "capture_top_processes", "find_unresponsive_windows", "find_process_autostart",
}


async def test_diagnose_toolset_is_read_only(deps):
    mcp = FastMCP("t")
    register_toolsets(mcp, deps, ("common", "diagnose"))
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) == ALL
    assert all(t.annotations.readOnlyHint for t in tools.values())  # diagnose is read-only
    assert tools["analyze_metric_periodicity"].annotations.readOnlyHint is True
    # Context parameter must not leak into the schema the LLM sees
    assert "ctx" not in tools["capture_top_processes"].inputSchema["properties"]


CONTROL = {
    "get_device_capabilities", "take_screenshot", "request_kill_process", "request_power_action", "request_set_data",
    "request_kvm_session", "request_protection_action", "request_recovery_action", "confirm_action",
    "find_wol_relay_candidates", "request_configure_wol", "wait_for_device_online", "request_disable_autostart",
}


async def test_control_toolset_adds_confirm_action(deps):
    mcp = FastMCP("t")
    register_toolsets(mcp, deps, ("control",))
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) == CONTROL | {"list_devices"}
    assert tools["confirm_action"].annotations.destructiveHint is True
    assert tools["confirm_action"].inputSchema["required"] == ["confirm_token"]
    # every step-1 tool is read-only: it must never change device state
    assert all(tools[n].annotations.readOnlyHint for n in CONTROL if n.startswith("request_"))


async def test_entry_point_tools_skip_deferred_loading(deps):
    mcp = FastMCP("t")
    register_toolsets(mcp, deps, ("common", "diagnose", "control"))
    always = {t.name for t in await mcp.list_tools() if (t.meta or {}).get("anthropic/alwaysLoad")}
    assert always == {"list_devices", "get_device_capabilities", "confirm_action"}


async def test_toolset_filter_exposes_only_common(deps):
    mcp = FastMCP("t")
    enabled = register_toolsets(mcp, deps, ("common",))
    assert enabled == ["common"]
    assert {t.name for t in await mcp.list_tools()} == {"list_devices"}


async def test_call_tool_through_mcp(deps):
    mcp = FastMCP("t")
    register_toolsets(mcp, deps, ("diagnose",))
    out = await mcp.call_tool("analyze_metric_periodicity", {"did": 7})
    content = out[0] if isinstance(out, tuple) else out
    payload = json.loads(content[0].text)
    assert payload["periodic"] is True
    assert abs(payload["period_sec"] - 180) <= 5
