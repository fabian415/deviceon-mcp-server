"""Client for DeviceOn's remote terminal websocket (Terminal.java, 'terminal' agent plugin).

Verified on a Windows 10 agent (2026-11): the agent runs ONE persistent cmd.exe as
NT AUTHORITY\\SYSTEM in session 0 per terminal session, echoes each command, and streams
the output back in chunks followed by a "C:\\...>" prompt. There is no end-of-output
marker, so every command is suffixed with "& echo <sentinel>" and we read until the
sentinel line arrives.

URL (from the portal's WebShell.js, NOT the apidoc): <ws|wss>://<host>/terminal/<auth>/<agentId>/<uuid>
with no /rmm context path. <auth> is the HTTP Basic value base64(user:password), or "-1"
with an EIRMMToken cookie when using a token.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import ssl
import time
import uuid
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import websockets

from .config import Settings

SENTINEL = "__DOMCP_END_"


@dataclass
class TerminalResult:
    output: str
    completed: bool        # False when the sentinel never arrived (timeout)
    duration_sec: float


class TerminalError(Exception):
    pass


_CLIXML = re.compile(r"#< CLIXML\s*|<Objs Version=.*?</Objs>", flags=re.S)


def marker_regex(marker: str) -> re.Pattern[str]:
    """The sentinel at the end of a line, but not the echoed '... & echo <marker>' command line.

    It is not always at the start of a line: PowerShell may print progress CLIXML without a
    trailing newline right before it.
    """
    return re.compile(rf"(?<!echo ){re.escape(marker)}\s*$", flags=re.M)


def clean_output(raw: str, cmdline: str, marker: str) -> str:
    """Drop the banner, the echoed command line, the sentinel, the trailing prompt and CLIXML noise."""
    text = raw.replace("\r\n", "\n")
    echo_at = text.find(f"echo {marker}")
    if echo_at >= 0:
        nl = text.find("\n", echo_at)
        text = text[nl + 1:] if nl >= 0 else ""
    else:
        first = cmdline[:40]
        idx = text.find(first)
        if idx >= 0:
            nl = text.find("\n", idx)
            text = text[nl + 1:] if nl >= 0 else ""
    m = marker_regex(marker).search(text)
    if m:
        text = text[: m.start()]
    return _CLIXML.sub("", text).strip("\n").rstrip()


class TerminalClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _url_and_headers(self, agent_id: str) -> tuple[str, dict[str, str]]:
        s = self._settings
        parts = urlsplit(s.base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        headers: dict[str, str] = {}
        if s.token:
            auth = "-1"
            headers["Cookie"] = f"EIRMMToken={s.token}"
        else:
            auth = quote(base64.b64encode(f"{s.username}:{s.password}".encode()).decode(), safe="")
        return f"{scheme}://{parts.netloc}/terminal/{auth}/{agent_id}/{uuid.uuid4()}", headers

    def _ssl(self) -> ssl.SSLContext | None:
        if not self._settings.base_url.startswith("https"):
            return None
        ctx = ssl.create_default_context()
        if not self._settings.verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def run(self, agent_id: str, cmdline: str, timeout_sec: float = 60, windows: bool = True) -> TerminalResult:
        """Run one command line in a fresh terminal session and return its output."""
        marker = f"{SENTINEL}{uuid.uuid4().hex[:10]}__"
        sep = " & " if windows else " ; "
        full = f"{cmdline}{sep}echo {marker}"
        url, headers = self._url_and_headers(agent_id)
        started = time.monotonic()
        chunks: list[str] = []
        try:
            async with websockets.connect(url, ssl=self._ssl(), additional_headers=headers, open_timeout=20,
                                          max_size=16 * 1024 * 1024) as ws:
                await ws.send(json.dumps({"reqId": 1, "cmdstr": full, "tmnWidth": 100, "tmnHeight": 100}))
                deadline = started + timeout_sec
                done = marker_regex(marker)
                try:
                    while True:
                        left = deadline - time.monotonic()
                        if left <= 0:
                            break
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=left))
                        content = ((msg.get("content") or {}).get("terminalTiInfo") or {}).get("terminalContent")
                        if content:
                            chunks.append(content)
                            if done.search("".join(chunks).replace("\r\n", "\n")):
                                break
                except asyncio.TimeoutError:
                    pass
                finally:
                    try:
                        await ws.send(json.dumps({"reqId": 2}))  # stop the agent-side shell
                    except websockets.ConnectionClosed:
                        pass
        except (OSError, websockets.InvalidHandshake, websockets.ConnectionClosed) as ex:
            raise TerminalError(f"terminal connection failed: {ex}") from ex
        raw = "".join(chunks)
        completed = bool(marker_regex(marker).search(raw.replace("\r\n", "\n")))
        return TerminalResult(clean_output(raw, full, marker), completed, round(time.monotonic() - started, 1))
