"""Shared dependencies handed to every toolset's register() function."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import asyncio

from .client import DeviceOnClient
from .config import Settings
from .confirm_store import ConfirmStore


@dataclass
class Deps:
    settings: Settings
    client: DeviceOnClient
    confirm: ConfirmStore
    # Injected so tests can run without real waiting / wall-clock time.
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep)
    now_ms: Callable[[], int] = field(default=lambda: int(time.time() * 1000))


# Optional progress callback: (progress, total, message)
ProgressFn = Callable[[float, float, str], Awaitable[None]]
