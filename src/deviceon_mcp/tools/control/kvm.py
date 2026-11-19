"""Start a remote-desktop (VNC) session for a human operator."""

from __future__ import annotations

import secrets

from mcp.server.fastmcp.exceptions import ToolError

from ...actions import issue_action
from ...client import DeviceOnError
from ...deps import Deps
from ..common.devices import device_ref, get_device_checked, require_online

ACTION = "kvm"
PLUGIN = "remote_kvm"
MODES = {"p2p": 1, "repeater": 3}
# The portal's KVM is served to the browser through noVNC (port 80 is its web port); UltraVNC and other
# native VNC viewers cannot connect to the returned host/port.
NOVNC_NOTE = ("the returned host/port (port 80) is for the portal's browser-based noVNC client; "
              "UltraVNC is not supported.")


async def request_kvm_session(
    deps: Deps, did: int, mode: str = "repeater", repeater_id: int | None = None,
    force_restart_vnc: bool = False, reason: str = "",
) -> dict:
    if mode not in MODES:
        raise ToolError(f"mode must be one of {', '.join(MODES)}")
    dev = await get_device_checked(deps, did, require_plugin=PLUGIN)
    require_online(dev, "a remote-desktop session")
    if mode == "repeater" and repeater_id is None:
        repeater_id = 10_000 + secrets.randbelow(90_000)
    summary = {"device": device_ref(dev), "mode": mode, "repeater_id": repeater_id if mode == "repeater" else None,
               "force_restart_vnc": force_restart_vnc, "reason": reason or None}
    warnings = [
        "Opens a remote-desktop (VNC) channel: whoever has the connection details can see and control the "
        "device's desktop while the session is open.",
        "An AI agent cannot use this session; the result is connection details for a human, who opens it "
        "in the DeviceOn portal's browser KVM page (noVNC). Native VNC viewers such as UltraVNC are not supported.",
    ]
    if force_restart_vnc:
        warnings.append("Restarts the WinVNC service on the device, dropping any existing remote session.")
    params = {"agent_id": dev["agentId"], "mode": MODES[mode], "repeater_id": repeater_id if mode == "repeater" else None,
              "force_restart_vnc": force_restart_vnc}
    return await issue_action(deps, ACTION, params, summary, warnings)


async def execute(deps: Deps, params: dict) -> dict:
    try:
        resp = await deps.client.start_kvm(params["agent_id"], params["mode"], params["repeater_id"],
                                           params["force_restart_vnc"])
    except DeviceOnError as ex:
        raise ToolError(f"starting the KVM session failed: {ex}") from ex
    port = resp.get("port")
    result = {
        "status": "started",
        "connection": {"host": resp.get("IP"), "port": port, "kvm_mode": resp.get("KVMmode"),
                       "repeater_id": params["repeater_id"]},
        "portal_response": resp,
        "next_step": "Tell the user to open the device's KVM page in the DeviceOn portal (browser, noVNC). "
                     "Do not tell them to connect with UltraVNC or another native VNC viewer: "
                     + NOVNC_NOTE,
    }
    if str(port) == "80":
        result["port_note"] = "Port 80 is the web port for the portal's browser-based noVNC client, not a raw " \
                              "VNC (RFB) port; UltraVNC cannot connect to it."
    return result
