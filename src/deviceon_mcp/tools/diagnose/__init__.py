"""Toolset 'diagnose': read-only. Find recurring resource spikes, the process behind them, and hung
windows. Stopping a process lives in toolset 'control' (request_kill_process)."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ...deps import Deps
from . import autostart, metrics, processes, windows

Did = Annotated[int, Field(description="Device id (did) from list_devices")]


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool(annotations=ToolAnnotations(title="Analyze metric periodicity", readOnlyHint=True, openWorldHint=False))
    async def analyze_metric_periodicity(
        did: Did,
        sensor: Annotated[str, Field(description="'cpu' (default), 'memory' (physical memory usage %), 'temperature', or '<plugin>:<sensorId>' e.g. 'ProcessMonitor:/System Monitor Info/CPU Usage'")] = "cpu",
        window_min: Annotated[int, Field(description="History window in minutes (5-1440). Use a window covering at least 4 suspected periods.")] = 30,
        min_amplitude: Annotated[float, Field(description="Minimum spike height above baseline to count as anomalous, in sensor units (default 20 = 20 percentage points for cpu/memory). Idle memory usage can drift 5-10 points, so do not go much below 10 for memory.")] = 20.0,
    ) -> dict:
        """Check a device's metric history for spikes and whether they recur periodically.

        Use when a device is reported slow/hot/unstable, or to verify a fix. The server
        does the math and returns a summary: periodic, period_sec, peak_avg, baseline,
        duty_cycle, confidence, next_peak_eta_sec, plus notes about data quality. Read
        the notes before drawing conclusions. If cpu looks normal but the device is still
        reported unstable, also check sensor='memory'. Does not identify the cause; follow up
        with capture_top_processes (metric matching the sensor).
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
        metric: Annotated[Literal["cpu", "memory"], Field(description="Which spikes to explain: 'cpu' (default) or 'memory'. Use the one whose analyze_metric_periodicity result was anomalous.")] = "cpu",
    ) -> dict:
        """Sample a device's process list repeatedly and rank processes by how well their CPU or memory tracks the system's spikes.

        Returns top_processes (cpu: avg_cpu, avg_cpu_during_spike; memory: growth_mb,
        spike_delta_mb; both: correlation), top_process_groups (same-name processes running
        at once) and a 'suspect' when the evidence is clear. A suspect with a
        recurrence_hint was restarted or short-lived during the capture (likely scheduled):
        tell the user killing it only ends the current run. This call blocks for
        duration_sec. Read-only; to stop a process use request_kill_process (toolset 'control').
        """
        async def progress(done: float, total: float, msg: str) -> None:
            await ctx.report_progress(done, total, msg)

        return await processes.capture_top_processes(
            deps, did, duration_sec, samples, top_n, metric=metric, progress=progress
        )

    @mcp.tool(annotations=ToolAnnotations(title="Find unresponsive windows", readOnlyHint=True, openWorldHint=False))
    async def find_unresponsive_windows(did: Did) -> dict:
        """List application windows on a Windows device that are 'Not Responding' (hung).

        Use when the user says a program is frozen/stuck but CPU and memory look normal: a
        deadlocked or I/O-blocked GUI app shows ~0% CPU, so the metric tools cannot find it.
        Runs a fixed read-only check in the logged-on user's session (~3-10 s). Returns
        not_responding entries with pid, name and window title.
        """
        return await windows.find_unresponsive_windows(deps, did)

    @mcp.tool(annotations=ToolAnnotations(title="Find process autostart", readOnlyHint=True, openWorldHint=False))
    async def find_process_autostart(
        did: Did,
        names: Annotated[list[str], Field(description="1-5 program file names, e.g. ['pressure_leak.exe'] (from analyze_last_shutdown suspects or capture_top_processes)")],
    ) -> dict:
        """Find what starts a program automatically on a Windows device: scheduled tasks, services, Run keys, Startup folders.

        Use when a culprit process keeps coming back (after a kill or a reboot): killing it
        only helps until the next start. Also lists running instances with their parent.
        Read-only (~5-15 s). To turn a task/service off use request_disable_autostart
        (toolset 'control').
        """
        return await autostart.find_process_autostart(deps, did, names)
