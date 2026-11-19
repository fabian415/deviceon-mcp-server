"""Generic two-step actions shared by every toolset that changes device state.

A request_* tool validates its input, builds a human-readable summary and calls
issue_action(), which stores the parameters behind a single-use confirm token. Nothing
reaches the device until confirm_action(token) runs the registered executor. The agent
therefore cannot act without first passing through a step that tells it to ask the user.

Toolsets register their executors in register_action() at start-up; confirm_action only
accepts tokens of registered action types.

YOLO mode (DEVICEON_AUTO_CONFIRM): for the listed action names (or "all"), issue_action
runs the executor immediately instead of returning a token. All request-time checks
(protected processes, pid reuse, refused scripts, ...) still apply; a request flagged with
auto_ok=False (e.g. a script matching risk patterns) still falls back to asking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .deps import Deps

log = logging.getLogger("deviceon_mcp.audit")

Executor = Callable[[Deps, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ActionSpec:
    title: str          # shown to the user, e.g. "Restart device"
    execute: Executor   # receives the params stored at request time


def register_action(deps: Deps, name: str, title: str, execute: Executor) -> None:
    deps.actions[name] = ActionSpec(title, execute)


def is_auto_confirmed(deps: Deps, name: str) -> bool:
    auto = deps.settings.auto_confirm
    return "all" in auto or name in auto


def check_auto_confirm(deps: Deps) -> None:
    """Called once all toolsets are registered: reject typos in DEVICEON_AUTO_CONFIRM."""
    unknown = sorted(deps.settings.auto_confirm - {"all"} - set(deps.actions))
    if unknown:
        raise RuntimeError(
            f"DEVICEON_AUTO_CONFIRM has unknown or not-enabled action(s): {', '.join(unknown)}; "
            f"enabled actions: {', '.join(sorted(deps.actions)) or '(none)'}, or 'all'"
        )
    if deps.settings.auto_confirm:
        enabled = sorted(a for a in deps.actions if is_auto_confirmed(deps, a))
        log.warning("YOLO mode: these actions run WITHOUT confirmation: %s", ", ".join(enabled))


def request_annotations(deps: Deps, name: str, title: str) -> ToolAnnotations:
    """Annotations for a request_* tool: read-only normally, destructive when it auto-executes."""
    if is_auto_confirmed(deps, name):
        return ToolAnnotations(title=f"{title} (auto-confirmed)", readOnlyHint=False, destructiveHint=True,
                               idempotentHint=False, openWorldHint=False)
    return ToolAnnotations(title=f"{title} (step 1 of 2)", readOnlyHint=True, openWorldHint=False)


async def issue_action(
    deps: Deps,
    name: str,
    params: dict[str, Any],
    summary: dict[str, Any],
    warnings: list[str] | None = None,
    auto_ok: bool = True,
) -> dict[str, Any]:
    spec: ActionSpec = deps.actions[name]
    log.info("action requested %s params=%s", name, params)
    if auto_ok and is_auto_confirmed(deps, name):
        log.warning("action auto-confirmed (YOLO) %s params=%s", name, params)
        result = await _execute(deps, spec, name, params)
        return {"action": spec.title, "auto_confirmed": True, "summary": summary,
                "warnings": warnings or [], **result}
    token = deps.confirm.issue(name, params, summary)
    out = {
        "confirm_token": token,
        "expires_in_sec": deps.confirm.ttl_sec,
        "action": spec.title,
        "summary": summary,
        "warnings": warnings or [],
        "instruction": (
            "Nothing has been done yet. Show the action, summary and warnings to the user and ask for "
            "explicit confirmation. Call confirm_action with this token ONLY after the user agrees; "
            "if they decline, do nothing."
        ),
    }
    if is_auto_confirmed(deps, name):
        out["auto_confirm_skipped"] = ("Auto-confirm is on for this action, but this request was flagged as risky "
                                       "(see warnings), so it still needs the user's explicit approval.")
    return out


async def confirm_action(deps: Deps, confirm_token: str) -> dict[str, Any]:
    try:
        pending = deps.confirm.consume_any(confirm_token, frozenset(deps.actions))
    except KeyError as ex:
        raise ToolError(f"{ex.args[0]}. Call the matching request_* tool again.") from ex
    spec: ActionSpec = deps.actions[pending.action]
    log.info("action confirmed %s params=%s", pending.action, pending.params)
    result = await _execute(deps, spec, pending.action, pending.params)
    return {"action": spec.title, "summary": pending.summary, **result}


async def _execute(deps: Deps, spec: ActionSpec, name: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await spec.execute(deps, params)
    except ToolError:
        log.warning("action failed %s params=%s", name, params)
        raise
    log.info("action done %s status=%s", name, result.get("status"))
    return result
