"""Toolset 'diagnose': find recurring resource spikes, the process behind them, and stop it."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ...deps import Deps
from . import metrics, processes

Did = Annotated[int, Field(description="Device id (did) from list_devices")]


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool(annotations=ToolAnnotations(title="Analyze metric periodicity", readOnlyHint=True, openWorldHint=False))
    async def analyze_metric_periodicity(
        did: Did,
        sensor: Annotated[str, Field(description="'cpu' (default), 'temperature', or '<plugin>:<sensorId>' e.g. 'ProcessMonitor:/System Monitor Info/CPU Usage'")] = "cpu",
        window_min: Annotated[int, Field(description="History window in minutes (5-1440). Use a window covering at least 4 suspected periods.")] = 30,
        min_amplitude: Annotated[float, Field(description="Minimum spike height above baseline to count as anomalous, in sensor units (default 20 = 20 CPU % points)")] = 20.0,
    ) -> dict:
        """Check a device's metric history for spikes and whether they recur periodically.

        Use when a device is reported slow/hot/unstable, or to verify a fix. The server
        does the math and returns a summary: periodic, period_sec, peak_avg, baseline,
        duty_cycle, confidence, next_peak_eta_sec, plus notes about data quality. Read
        the notes before drawing conclusions. Does not identify the cause; follow up with
        capture_top_processes.
        """
        return await metrics.analyze_metric_periodicity(deps, did, sensor, window_min, min_amplitude)

    @mcp.tool(annotations=ToolAnnotations(title="Get current metrics", readOnlyHint=True, openWorldHint=False))
    async def get_current_metrics(did: Did) -> dict:
        """Get a device's latest CPU usage, memory and temperatures (if a temperature sensor exists).

        A single point-in-time reading; use analyze_metric_periodicity for trends.
        """
        return await metrics.get_current_metrics(deps, did)

    @mcp.tool(annotations=ToolAnnotations(title="Capture top processes", readOnlyHint=True, openWorldHint=False))
    async def capture_top_processes(
        did: Did,
        ctx: Context,
        duration_sec: Annotated[int, Field(description="How long to sample (5-600). Must cover a spike: use >= period_sec, or start when next_peak_eta_sec is small.")] = 60,
        samples: Annotated[int, Field(description="Number of process snapshots to take (3-60)")] = 12,
        top_n: Annotated[int, Field(description="How many processes to return (1-20)")] = 5,
    ) -> dict:
        """Sample a device's process list repeatedly and rank processes by how well their CPU tracks the system CPU spikes.

        Returns top_processes (pid, name, avg_cpu, avg_cpu_during_spike, correlation),
        top_process_groups (same-name multi-process programs) and a 'suspect' when the
        evidence is clear. This call blocks for duration_sec. Read-only; to stop a process
        use request_kill_process.
        """
        async def progress(done: float, total: float, msg: str) -> None:
            await ctx.report_progress(done, total, msg)

        return await processes.capture_top_processes(deps, did, duration_sec, samples, top_n, progress)

    @mcp.tool(annotations=ToolAnnotations(title="Request process kill (step 1 of 2)", readOnlyHint=True, openWorldHint=False))
    async def request_kill_process(
        did: Did,
        pid: Annotated[int, Field(description="Process id to stop, from capture_top_processes")],
        name: Annotated[str, Field(description="Expected process name; used to detect pid reuse")],
        reason: Annotated[str, Field(description="Short justification shown to the user, e.g. the evidence from capture_top_processes")] = "",
    ) -> dict:
        """Prepare to kill a process. Does NOT kill anything.

        Verifies the pid/name are still running and not protected, then returns a
        confirm_token and a summary. You must show the summary to the user and get an
        explicit yes before calling confirm_kill_process. The token expires after a few minutes.
        """
        return await processes.request_kill_process(deps, did, pid, name, reason)

    @mcp.tool(annotations=ToolAnnotations(title="Confirm process kill (step 2 of 2)", readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
    async def confirm_kill_process(
        confirm_token: Annotated[str, Field(description="Token returned by request_kill_process")],
        verify_timeout_sec: Annotated[int, Field(description="How long to wait for the process to disappear (5-120)")] = 30,
    ) -> dict:
        """Kill the process approved by the user. Only call after the user explicitly agreed.

        Re-checks that the pid still belongs to the same process name (aborts if the pid
        was reused or it already exited), sends the kill, and verifies it is gone.
        Tokens are single-use.
        """
        return await processes.confirm_kill_process(deps, confirm_token, verify_timeout_sec)
