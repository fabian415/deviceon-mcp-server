"""Toolset registry. Each toolset is a sub-package exposing register(mcp, deps).

Add a new domain (e.g. 'ota', 'container', 'audit') by creating tools/<name>/ with a
register() function and listing it here. Which toolsets are exposed is controlled by
DEVICEON_TOOLSETS, so an agent handling a diagnose ticket never sees OTA tools.
"""

from __future__ import annotations

from typing import Callable

from mcp.server.fastmcp import FastMCP

from ..actions import check_auto_confirm
from ..deps import Deps
from . import common, control, diagnose, logs, remote

TOOLSETS: dict[str, Callable[[FastMCP, Deps], None]] = {
    "common": common.register,
    "diagnose": diagnose.register,
    "control": control.register,
    "logs": logs.register,
    "remote": remote.register,  # also needs DEVICEON_ALLOW_REMOTE_COMMAND=true
}


def register_toolsets(mcp: FastMCP, deps: Deps, names: tuple[str, ...]) -> list[str]:
    unknown = [n for n in names if n not in TOOLSETS]
    if unknown:
        raise RuntimeError(f"unknown toolset(s): {', '.join(unknown)}; available: {', '.join(TOOLSETS)}")
    # 'common' is always included: every other toolset needs device lookup.
    ordered = ["common"] + [n for n in names if n != "common"]
    for name in ordered:
        TOOLSETS[name](mcp, deps)
    if deps.actions:  # some toolset registered request_* tools that need step 2
        common.register_confirm_action(mcp, deps)
    check_auto_confirm(deps)
    return ordered
