"""Toolset 'common': tools every task needs (device lookup)."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ...deps import Deps
from . import devices


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool(annotations=ToolAnnotations(title="List devices", readOnlyHint=True, openWorldHint=False))
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
