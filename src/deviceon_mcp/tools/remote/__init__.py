"""Toolset 'remote': run AI-written scripts on a device (approach C, human-approved).

Needs BOTH DEVICEON_TOOLSETS to include 'remote' AND DEVICEON_ALLOW_REMOTE_COMMAND=true.
Every script goes through request_run_command (shows the full script, flags risky
patterns, refuses encoded commands) and runs only after confirm_action.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ...actions import register_action, request_annotations
from ...deps import Deps
from ...remote_exec import MAX_SCRIPT
from . import command


def register(mcp: FastMCP, deps: Deps) -> None:
    if not deps.settings.allow_remote_command:
        raise RuntimeError("toolset 'remote' also requires DEVICEON_ALLOW_REMOTE_COMMAND=true")
    register_action(deps, command.ACTION, "Run command on device", command.execute)

    @mcp.tool(annotations=request_annotations(deps, command.ACTION, "Request run command"))
    async def request_run_command(
        did: Annotated[int, Field(description="Device id (did) from list_devices")],
        script: Annotated[str, Field(description=f"The script to run, in plain text (max {MAX_SCRIPT} chars). "
                                                 "PowerShell may span several lines; cmd/sh must be one line.")],
        shell: Annotated[Literal["powershell", "cmd", "sh"], Field(description="powershell (default) or cmd on Windows; sh on Linux")] = "powershell",
        run_as: Annotated[Literal["system", "user"], Field(
            description="'system' (default): NT AUTHORITY\\SYSTEM via the remote terminal, fast, sees services/files but "
                        "NOT the user's windows. 'user': the logged-on user's desktop session (Windows + powershell only); "
                        "needed for anything about their windows, e.g. Get-Process ... Responding/MainWindowTitle.")] = "system",
        timeout_sec: Annotated[int, Field(description="How long to wait for the output (5-300)")] = 60,
        reason: Annotated[str, Field(description="Why this script is needed; shown to the user")] = "",
    ) -> dict:
        """Prepare running a script you wrote on a device. Does NOT run it yet.

        Prefer the purpose-built tools (diagnose, control, fetch_device_log) when they fit;
        use this for anything they do not cover. Prefer read-only scripts. The summary shows
        the full script and risk warnings: show them to the user verbatim and call
        confirm_action only after an explicit yes. Encoded commands are refused. Returns the
        script's output (as text) after confirmation.
        """
        return await command.request_run_command(deps, did, script, shell, run_as, timeout_sec, reason)
