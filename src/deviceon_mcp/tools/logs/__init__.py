"""Toolset 'logs': read device event logs (read-only, fixed queries)."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ...deps import Deps
from . import eventlog


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool(annotations=ToolAnnotations(title="Fetch device log", readOnlyHint=True, openWorldHint=False))
    async def fetch_device_log(
        did: Annotated[int, Field(description="Device id (did) from list_devices")],
        log_name: Annotated[str, Field(description="Windows event log, e.g. 'System', 'Application', 'Security', "
                                                   "'Windows PowerShell' (get_device_capabilities lists the common ones)")] = "System",
        since_minutes: Annotated[int, Field(description="How far back to look, in minutes (1-10080)")] = 60,
        level: Annotated[Literal["critical", "error", "warning", "information", "verbose", "any"],
                         Field(description="Minimum severity: 'warning' returns critical+error+warning")] = "warning",
        contains: Annotated[str | None, Field(description="Only events whose message contains this text (case-insensitive)")] = None,
        max_events: Annotated[int, Field(description="Max events to return, newest first (1-100)")] = 50,
        source: Annotated[Literal["terminal", "devlog"], Field(
            description="'terminal' (default): fast query on the device. 'devlog': DeviceOn's Device Log upload "
                        "(slower; needs the portal's Device Log storage to work)")] = "terminal",
    ) -> dict:
        """Read recent events from a Windows device's event log, filtered on the device.

        Use it to find crashes, service failures, driver/disk errors or application errors
        around the time a problem was reported. Returns time, level, event id, source and a
        shortened message per event. Read-only.
        """
        return await eventlog.fetch_device_log(deps, did, log_name, since_minutes, level, contains, max_events, source)
