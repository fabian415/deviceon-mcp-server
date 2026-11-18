"""Single-use, expiring confirmation tokens for destructive actions.

request_kill_process issues a token; confirm_kill_process consumes it. Because the
kill tool only accepts a token (not a pid), the agent cannot kill anything without
first going through the request step that tells it to ask the user.

In-memory only: tokens die with the process, which is the safe default for a PoC.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingAction:
    action: str
    params: dict[str, Any]
    created_at: float
    expires_at: float
    summary: dict[str, Any] = field(default_factory=dict)


class ConfirmStore:
    def __init__(self, ttl_sec: int, clock=time.monotonic):
        self._ttl = ttl_sec
        self._clock = clock
        self._items: dict[str, PendingAction] = {}
        self._lock = threading.Lock()

    @property
    def ttl_sec(self) -> int:
        return self._ttl

    def issue(self, action: str, params: dict[str, Any], summary: dict[str, Any] | None = None) -> str:
        now = self._clock()
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._purge(now)
            self._items[token] = PendingAction(action, params, now, now + self._ttl, summary or {})
        return token

    def consume(self, token: str, action: str) -> PendingAction:
        """Return and remove the pending action; raises KeyError if unknown, expired or wrong type."""
        now = self._clock()
        with self._lock:
            self._purge(now)
            item = self._items.get(token)
            if item is None or item.action != action:
                raise KeyError("confirm_token is unknown, already used, or expired")
            del self._items[token]
            return item

    def _purge(self, now: float) -> None:
        for k in [k for k, v in self._items.items() if v.expires_at <= now]:
            del self._items[k]
