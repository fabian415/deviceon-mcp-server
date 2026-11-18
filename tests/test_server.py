"""MCP-level checks: toolset registration, schemas, annotations, and a call through FastMCP."""

import json

from mcp.server.fastmcp import FastMCP

from deviceon_mcp.tools import register_toolsets

ALL = {
    "list_devices", "analyze_metric_periodicity", "get_current_metrics",
    "capture_top_processes", "request_kill_process", "confirm_kill_process",
}


async def test_all_toolsets_register_six_tools(deps):
    mcp = FastMCP("t")
    register_toolsets(mcp, deps, ("common", "diagnose"))
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) == ALL
    assert tools["confirm_kill_process"].annotations.destructiveHint is True
    assert tools["analyze_metric_periodicity"].annotations.readOnlyHint is True
    # Context parameter must not leak into the schema the LLM sees
    assert "ctx" not in tools["capture_top_processes"].inputSchema["properties"]
    assert tools["confirm_kill_process"].inputSchema["required"] == ["confirm_token"]


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
