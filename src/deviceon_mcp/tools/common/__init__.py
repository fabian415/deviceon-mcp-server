"""Toolset 'common': tools every task needs (device lookup)."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ... import actions
from ...deps import Deps
from . import devices

# Claude Code defers MCP tools behind tool search by default; entry points the model needs
# in almost every task load up front so it does not spend a search step on them.
ALWAYS_LOAD = {"anthropic/alwaysLoad": True}


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool(annotations=ToolAnnotations(title="List devices", readOnlyHint=True, openWorldHint=False), meta=ALWAYS_LOAD)
    async def list_devices(
        filter: Annotated[str | None, Field(description="Substring to match, e.g. part of the device name. Omit to list all.")] = None,
        field: Annotated[str, Field(description="Which attribute 'filter' matches: name, agentId, mac, localIP, platformName, osType, osArch")] = "name",
        connected_only: Annotated[bool, Field(description="Only return devices currently online")] = False,
        limit: Annotated[int, Field(description="Max devices to return (1-100)")] = 20,
    ) -> dict:
        """Find DeviceOn devices and their numeric device id (did).

        Use this first whenever the user refers to a device by name, IP or MAC; every
        other tool needs the did. 'canDiagnoseProcesses' tells whether the device has
        the ProcessMonitor plugin required by the diagnose tools.
        """
        return await devices.list_devices(deps, filter, field, connected_only, limit)


def register_confirm_action(mcp: FastMCP, deps: Deps) -> None:
    """Registered by register_toolsets only when some enabled toolset has confirmable actions."""

    @mcp.tool(annotations=ToolAnnotations(title="Confirm action (step 2 of 2)", readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False), meta=ALWAYS_LOAD)
    async def confirm_action(
        confirm_token: Annotated[str, Field(description="Token returned by a request_* tool")],
    ) -> dict:
        """Carry out an action prepared by a request_* tool. Only call after the user explicitly agreed.

        Works for every request_* tool (kill, power, data, KVM, protection, recovery, run command).
        Tokens are single-use and expire after a few minutes.
        """
        return await actions.confirm_action(deps, confirm_token)
