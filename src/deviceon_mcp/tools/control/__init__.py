"""Toolset 'control': device-level commands (process kill, power, screenshot, data, KVM, protection, recovery).

Every state-changing tool here is step 1 of 2: it validates, returns a summary and a
confirm_token, and does nothing else. The change happens only in confirm_action (toolset
'common') after the user agrees. Group-wide variants of these APIs are deliberately not
exposed: one confirmation should never fan out to a whole fleet.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from pydantic import Field

from ...actions import register_action, request_annotations
from ...deps import Deps
from ..common import ALWAYS_LOAD
from . import capabilities, data, kill, kvm, power, protect, screenshot

Did = Annotated[int, Field(description="Device id (did) from list_devices")]
Reason = Annotated[str, Field(description="Short justification shown to the user")]

def register(mcp: FastMCP, deps: Deps) -> None:
    register_action(deps, kill.ACTION, "Kill process", kill.execute)
    register_action(deps, power.ACTION, "Device power action", power.execute)
    register_action(deps, data.ACTION, "Set device data", data.execute)
    register_action(deps, kvm.ACTION, "Start remote-desktop (KVM) session", kvm.execute)
    register_action(deps, protect.PROTECTION_ACTION, "Protection action", protect.execute_protection)
    register_action(deps, protect.RECOVERY_ACTION, "Backup / recovery action", protect.execute_recovery)

    @mcp.tool(annotations=ToolAnnotations(title="Get device capabilities", readOnlyHint=True, openWorldHint=False), meta=ALWAYS_LOAD)
    async def get_device_capabilities(did: Did) -> dict:
        """List which control tools work on a device right now and with which options.

        Call this before any control action: it reports supported power actions (and which
        are usable given online/offline), screenshot/KVM availability, protection and
        recovery status with allowed actions, device-log event types, and remote-command
        support. Read-only.
        """
        return await capabilities.get_device_capabilities(deps, did)

    @mcp.tool(annotations=request_annotations(deps, kill.ACTION, "Request process kill"))
    async def request_kill_process(
        did: Did,
        pid: Annotated[int, Field(description="Process id to stop, from capture_top_processes or find_unresponsive_windows")],
        name: Annotated[str, Field(description="Expected process name; used to detect pid reuse")],
        reason: Annotated[str, Field(description="Short justification shown to the user, e.g. the evidence that points at this process")] = "",
        verify_timeout_sec: Annotated[int, Field(description="After the kill, how long to wait for proof the process is gone (5-120)")] = 30,
    ) -> dict:
        """Prepare to kill a process. Does NOT kill anything.

        Verifies the pid/name are still running and not a protected system/agent process,
        then returns a confirm_token and a summary. Show it to the user and call
        confirm_action only after an explicit yes. At confirm time the pid is checked again
        (aborts if it exited or was reused) and the kill is verified afterwards.
        """
        return await kill.request_kill_process(deps, did, pid, name, reason, verify_timeout_sec)

    @mcp.tool(annotations=ToolAnnotations(title="Take screenshot", readOnlyHint=True, openWorldHint=False))
    async def take_screenshot(did: Did):
        """Capture the device's current desktop and return it as an image you can look at.

        Useful to see what the operator sees: error dialogs, a window marked 'Not Responding',
        a frozen UI. Returns captured=false when no user is logged on. Read-only, but it shows
        whatever is on screen, so only use it when it helps the user's request.
        """
        img, fmt, info = await screenshot.take_screenshot(deps, did)
        return [info, Image(data=img, format=fmt)] if img is not None else info

    @mcp.tool(annotations=request_annotations(deps, power.ACTION, "Request power action"))
    async def request_power_action(
        did: Did,
        action: Annotated[Literal["shutdown", "restart", "sleep", "hibernate", "start"],
                          Field(description="'start' = Wake-on-LAN (offline devices only); the others need the device online")],
        reason: Reason = "",
    ) -> dict:
        """Prepare a power action on one device. Does NOT do anything yet.

        Checks the device supports the action, then returns a confirm_token with a summary and
        warnings. Show them to the user; call confirm_action only after an explicit yes.
        """
        return await power.request_power_action(deps, did, action, reason)

    @mcp.tool(annotations=request_annotations(deps, data.ACTION, "Request set data"))
    async def request_set_data(
        did: Did,
        plugin: Annotated[str, Field(description="Plugin that owns the sensors, e.g. 'Modbus_Handler' (see get_device_capabilities plugins)")],
        values: Annotated[dict[str, bool | int | float | str],
                          Field(description="{sensorId: newValue}, sensorId as a path like '/Holding Registers/Data0'")],
        reason: Reason = "",
    ) -> dict:
        """Prepare writing values to a plugin's sensors or settings. Does NOT write yet.

        Reads the current values, refuses read-only or unknown sensors, matches value types,
        and returns a confirm_token with a current -> new summary. Call confirm_action only
        after the user agrees.
        """
        return await data.request_set_data(deps, did, plugin, values, reason)

    @mcp.tool(annotations=request_annotations(deps, kvm.ACTION, "Request KVM session"))
    async def request_kvm_session(
        did: Did,
        mode: Annotated[Literal["repeater", "p2p"], Field(description="'repeater' (default, works through NAT) or 'p2p'")] = "repeater",
        repeater_id: Annotated[int | None, Field(description="Repeater session id; generated when omitted")] = None,
        force_restart_vnc: Annotated[bool, Field(description="Restart the device's WinVNC service first")] = False,
        reason: Reason = "",
    ) -> dict:
        """Prepare a remote-desktop (VNC) session for a HUMAN operator. Does NOT open it yet.

        You cannot use the session yourself; after confirm_action you get host/port/repeater
        id to hand to the user. The user opens it in the DeviceOn portal's browser KVM page
        (noVNC; port 80 is its web port). UltraVNC and other native VNC viewers are NOT
        supported, so never tell the user to connect with one. Call confirm_action only
        after the user agrees.
        """
        return await kvm.request_kvm_session(deps, did, mode, repeater_id, force_restart_vnc, reason)

    @mcp.tool(annotations=request_annotations(deps, protect.PROTECTION_ACTION, "Request protection action"))
    async def request_protection_action(
        did: Did,
        action: Annotated[Literal["protect", "unprotect", "install", "update", "activate"],
                          Field(description="protect/unprotect need the software installed and activated")],
        reason: Reason = "",
    ) -> dict:
        """Prepare a protection (application lock-down) action. Does NOT do anything yet.

        Validates against the device's protection status and returns a confirm_token with a
        summary and warnings. Call confirm_action only after the user agrees.
        """
        return await protect.request_protection_action(deps, did, action, reason)

    @mcp.tool(annotations=request_annotations(deps, protect.RECOVERY_ACTION, "Request backup/recovery action"))
    async def request_recovery_action(
        did: Did,
        action: Annotated[Literal["backup", "recovery", "install", "update", "activate"],
                          Field(description="'recovery' restores the latest backup and discards later changes")],
        remote: Annotated[bool, Field(description="Back up to / restore from remote storage (backup/recovery only)")] = False,
        asz_percent: Annotated[int | None, Field(description="Secure-zone size as % of free disk (install only, 0-100)")] = None,
        reason: Reason = "",
    ) -> dict:
        """Prepare a backup / system-restore action. Does NOT do anything yet.

        Validates against the device's recovery status (and that a remote backup exists for a
        remote restore) and returns a confirm_token. Call confirm_action only after the user agrees.
        """
        return await protect.request_recovery_action(deps, did, action, remote, asz_percent, reason)



