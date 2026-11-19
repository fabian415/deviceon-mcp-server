"""Run scripts on a device and get their output back. Verified on a Windows 10 agent (2026-11).

Two channels, picked by who must run the script:

run_as="system"  -> remote terminal websocket (NT AUTHORITY\\SYSTEM, session 0).
                    Output comes straight back. Cannot see the user's windows.
run_as="user"    -> 1. terminal writes the script to C:\\ProgramData\\DeviceOnMCP\\<id>.ps1
                    2. POST /processes (Launch Remote Process) runs it with -File in the
                       logged-on user's session (verified: user advantech, session 1)
                    3. the script writes its output to the Application event log
                       (WScript.Shell.LogEvent, source WSH, tagged with <id>)
                    4. terminal waits for that event, prints it and deletes the .ps1.
                    The detour exists because Launch Remote Process returns no output and
                    rejects args longer than ~260 chars; the event log works for a
                    standard user, and DeviceOn's own log upload (devlog) was broken on
                    the test server ("Copyfile fail").

Limits found on the real system: a terminal websocket message must stay under ~8 KB
(server closes with 1009), so command lines are capped at MAX_CMDLINE.
"""

from __future__ import annotations

import base64
import re
import secrets
from dataclasses import dataclass

from .deps import Deps
from .terminal import TerminalError, TerminalResult

MAX_CMDLINE = 7_500          # chars of the cmd.exe line sent through the terminal websocket
MAX_SCRIPT = 2_500           # chars of user-supplied script (keeps encoded forms under MAX_CMDLINE)
MAX_OUTPUT = 20_000          # chars of output handed back to the LLM
EVENT_LIMIT = 30_000         # event log messages max out around 31 K chars
STAGE_DIR = r"C:\ProgramData\DeviceOnMCP"
EVENT_TAG = "DEVICEON-MCP"
PS_PREFIX = "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass"


class RemoteExecError(Exception):
    pass


@dataclass
class RunResult:
    status: str              # completed | timeout | launch_failed
    output: str
    truncated: bool
    duration_sec: float
    run_as: str
    detail: str | None = None

    def as_dict(self) -> dict:
        d = {"status": self.status, "run_as": self.run_as, "output": self.output,
             "output_truncated": self.truncated, "duration_sec": self.duration_sec}
        if self.detail:
            d["detail"] = self.detail
        return d


def is_windows(dev: dict) -> bool:
    return "windows" in str(dev.get("ostype") or "").lower()


def encode_ps(script: str) -> str:
    # Progress records (e.g. "Preparing modules for first use") would otherwise be printed as
    # CLIXML on stderr because the output is redirected.
    script = "$ProgressPreference='SilentlyContinue'\n" + script
    return f"{PS_PREFIX} -EncodedCommand " + base64.b64encode(script.encode("utf-16-le")).decode()


B64_TAG = "__DOMCP_B64__"
_B64_EMIT = f"'{B64_TAG}' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$o))"


def _wrap(script: str) -> str:
    """Run the user's script, merge errors into the output, render objects as text.

    The text is sent back base64(UTF-8): the terminal relays cmd.exe output in the OEM code
    page, which would turn non-ASCII characters into '?'.
    """
    return ("$o = try { & {\n" + script + "\n} 2>&1 | Out-String -Width 300 } catch { 'ERROR: ' + $_ }\n"
            + _B64_EMIT)


def decode_b64_output(text: str) -> str | None:
    """Return the decoded payload after B64_TAG, or None if the tag is missing."""
    idx = text.find(B64_TAG)
    if idx < 0:
        return None
    payload = re.match(r"[A-Za-z0-9+/=\s]*", text[idx + len(B64_TAG):]).group(0)  # type: ignore[union-attr]
    try:
        return base64.b64decode(re.sub(r"\s+", "", payload)).decode("utf-8", errors="replace")
    except (ValueError, base64.binascii.Error):
        return None


def _truncate(text: str) -> tuple[str, bool]:
    return (text, False) if len(text) <= MAX_OUTPUT else (text[:MAX_OUTPUT] + "\n...(truncated)", True)


def check_length(cmdline: str) -> None:
    if len(cmdline) > MAX_CMDLINE:
        raise RemoteExecError(f"script too long once encoded ({len(cmdline)} > {MAX_CMDLINE} chars); shorten it.")


def system_cmdline(script: str, shell: str) -> str:
    if shell == "powershell":
        cmd = encode_ps(_wrap(script))
    else:  # cmd / sh: passed to the agent's shell as-is (single line)
        cmd = script
    check_length(cmd)
    return cmd


def user_script_file(script: str, run_id: str) -> str:
    """Content of the staged .ps1: run the script, log its output to the event log."""
    return (
        "$ProgressPreference='SilentlyContinue'\n"
        "$r = try { & {\n" + script + "\n} 2>&1 | Out-String -Width 300 } catch { 'ERROR: ' + $_ }\n"
        f"if ($r.Length -gt {EVENT_LIMIT}) {{ $r = $r.Substring(0, {EVENT_LIMIT}) + \"`n...(truncated)\" }}\n"
        f"(New-Object -ComObject WScript.Shell).LogEvent(4, '{EVENT_TAG} {run_id}' + \"`n\" + $r) | Out-Null\n"
    )


def stage_cmdline(content: str, run_id: str) -> str:
    """cmd line that writes the .ps1 (UTF-8 with BOM so Windows PowerShell reads non-ASCII)."""
    b64 = base64.b64encode(content.encode("utf-8")).decode()
    path = f"{STAGE_DIR}\\{run_id}.ps1"
    cmd = (f'{PS_PREFIX} -Command "New-Item -ItemType Directory -Force \'{STAGE_DIR}\' | Out-Null; '
           f"[IO.File]::WriteAllText('{path}', [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}')), "
           f"(New-Object Text.UTF8Encoding $true)); 'staged'\"")
    check_length(cmd)
    return cmd


def wait_cmdline(run_id: str, wait_sec: int) -> str:
    """Poll the event log for the tagged event, print it, delete the staged script."""
    path = f"{STAGE_DIR}\\{run_id}.ps1"
    # Get-WinEvent with a provider/time filter is indexed; Get-EventLog scans the whole log.
    script = (
        f"$tag='{EVENT_TAG} {run_id}'; $m=$null; $since=(Get-Date).AddMinutes(-5)\n"
        f"for ($i=0; $i -lt {max(1, wait_sec // 2)} -and -not $m; $i++) {{\n"
        "  $e = Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='WSH'; StartTime=$since}"
        " -ErrorAction SilentlyContinue | Where-Object { $_.Message -like \"$tag*\" } | Select-Object -First 1\n"
        "  if ($e) { $m = $e.Message } else { Start-Sleep -Seconds 2 }\n"
        "}\n"
        f"Remove-Item -LiteralPath '{path}' -Force -ErrorAction SilentlyContinue\n"
        "if ($m) { $o = $m.Substring($tag.Length).TrimStart(\"`r\",\"`n\"); " + _B64_EMIT + " } else { '__DOMCP_NO_EVENT__' }"
    )
    cmd = encode_ps(script)
    check_length(cmd)
    return cmd


async def _terminal(deps: Deps, agent_id: str, cmdline: str, timeout: float, windows: bool = True) -> TerminalResult:
    try:
        return await deps.terminal.run(agent_id, cmdline, timeout, windows)
    except TerminalError as ex:
        raise RemoteExecError(str(ex)) from ex


async def run_system(deps: Deps, dev: dict, script: str, shell: str, timeout_sec: int) -> RunResult:
    cmd = system_cmdline(script, shell)
    r = await _terminal(deps, dev["agentId"], cmd, timeout_sec, windows=is_windows(dev))
    text = r.output
    if shell == "powershell":
        decoded = decode_b64_output(text)
        text = decoded if decoded is not None else text
    out, trunc = _truncate(text.strip("\r\n"))
    return RunResult("completed" if r.completed else "timeout", out, trunc, r.duration_sec, "system",
                     None if r.completed else f"no end marker within {timeout_sec}s; output may be partial")


async def run_user(deps: Deps, dev: dict, script: str, timeout_sec: int) -> RunResult:
    if not is_windows(dev):
        raise RemoteExecError("run_as='user' is only supported on Windows devices.")
    run_id = secrets.token_hex(6)
    agent_id = dev["agentId"]
    staged = await _terminal(deps, agent_id, stage_cmdline(user_script_file(script, run_id), run_id), 45)
    if not staged.completed or "staged" not in staged.output:
        raise RemoteExecError(f"could not stage the script on the device: {staged.output[-500:]!r}")
    path = f"{STAGE_DIR}\\{run_id}.ps1"
    launched = await deps.client.launch_process(
        agent_id, "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        f"-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File {path}", True)
    if launched.get("result") is False:
        await _terminal(deps, agent_id, f'del /q "{path}"', 30)
        return RunResult("launch_failed", "", False, staged.duration_sec, "user",
                         "the agent refused to start PowerShell in the user's session (no user logged on?)")
    waited = await _terminal(deps, agent_id, wait_cmdline(run_id, timeout_sec), timeout_sec + 30)
    decoded = decode_b64_output(waited.output)
    if decoded is not None:
        out, trunc = _truncate(decoded.strip("\r\n"))
        return RunResult("completed", out, trunc, round(staged.duration_sec + waited.duration_sec, 1), "user")
    return RunResult("timeout", "", False, round(staged.duration_sec + waited.duration_sec, 1), "user",
                     f"the script did not report back within {timeout_sec}s (still running, or no user logged on)")


# ---- static review of AI-written scripts ------------------------------------

_REFUSE = [
    (re.compile(r"(?i)(^|\s)-(e|ec|en|enc|enco|encod|encode|encoded|encodedc\w*)\s+[A-Za-z0-9+/=]{16,}"),
     "encoded commands (-EncodedCommand) hide what runs; write the script in plain text"),
]
_WARN = [
    (r"(?i)\b(remove-item|rm|rmdir|del|erase|rd)\b.*(-recurse|/s\b|-r\b)", "recursively deletes files"),
    (r"(?i)\bformat(-volume)?\b\s+[a-z]:|\bformat-volume\b|\bclear-disk\b|\bdiskpart\b", "formats or wipes a disk"),
    (r"(?i)\b(stop|restart)-computer\b|\bshutdown(\.exe)?\s+/[srpf]", "shuts down or restarts the device"),
    (r"(?i)\b(stop|restart|set)-service\b|\bsc(\.exe)?\s+(stop|delete|config)\b|\bnet\s+stop\b", "changes Windows services"),
    (r"(?i)\b(stop-process|taskkill|kill)\b", "kills processes"),
    (r"(?i)\breg(\.exe)?\s+(add|delete)\b|\b(set|new|remove)-itemproperty\b", "modifies the registry"),
    (r"(?i)\bnet\s+(user|localgroup)\b|\b(new|remove|add)-local(user|groupmember)\b", "changes user accounts"),
    (r"(?i)\b(invoke-webrequest|iwr|invoke-restmethod|irm|curl|wget|start-bitstransfer)\b", "downloads or sends data over the network"),
    (r"(?i)\b(invoke-expression|iex)\b|frombase64string", "runs dynamically built code"),
    (r"(?i)\bset-executionpolicy\b|\bnetsh\b|\bset-mppreference\b", "changes security settings"),
]


def review_script(script: str, protected: frozenset[str]) -> tuple[list[str], list[str]]:
    """Return (refusals, warnings) for an AI-written script."""
    refusals = [msg for rx, msg in _REFUSE if rx.search(script)]
    warnings = [f"script {msg}" for rx, msg in _WARN if re.search(rx, script)]
    lowered = script.lower()
    hit = sorted(p for p in protected if len(p) > 3 and re.search(rf"\b{re.escape(p)}\b", lowered))
    if hit:
        warnings.append(f"script mentions protected system/agent processes: {', '.join(hit)}")
    return refusals, warnings
