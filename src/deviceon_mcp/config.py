"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # Portal REST root, including the JAX-RS application path, e.g. https://deviceon.example.com/rmm
    base_url: str
    # Basic auth: DeviceOn account e-mail + plaintext password (see RMMLib AuthUtil.processLogin)
    username: str | None = None
    password: str | None = None
    # Or a pre-issued JWT, sent as "Authorization: Bearer <token>"
    token: str | None = None
    verify_tls: bool = True
    timeout_sec: int = 30
    # Which toolsets to expose, e.g. "common,diagnose"
    toolsets: tuple[str, ...] = ("common", "diagnose")
    # Kill confirmation token lifetime
    confirm_ttl_sec: int = 300
    # Optional fixed temperature source; otherwise auto-discovered from hardware-monitor plugins
    temp_plugin: str | None = None
    temp_sensor: str | None = None
    # Process names (case-insensitive) that may never be killed through this server
    protected_processes: frozenset[str] = field(default_factory=frozenset)

    @staticmethod
    def from_env() -> "Settings":
        base_url = os.environ.get("DEVICEON_BASE_URL", "").rstrip("/")
        if not base_url:
            raise RuntimeError("DEVICEON_BASE_URL is required, e.g. https://deviceon.example.com/rmm")
        username = os.environ.get("DEVICEON_USERNAME") or None
        password = os.environ.get("DEVICEON_PASSWORD") or None
        token = os.environ.get("DEVICEON_TOKEN") or None
        if not token and not (username and password):
            raise RuntimeError("Set DEVICEON_TOKEN, or both DEVICEON_USERNAME and DEVICEON_PASSWORD")

        toolsets = tuple(
            t.strip() for t in os.environ.get("DEVICEON_TOOLSETS", "common,diagnose").split(",") if t.strip()
        )
        extra_protected = {
            p.strip().lower() for p in os.environ.get("DEVICEON_PROTECTED_PROCESSES", "").split(",") if p.strip()
        }
        return Settings(
            base_url=base_url,
            username=username,
            password=password,
            token=token,
            verify_tls=_bool("DEVICEON_VERIFY_TLS", True),
            timeout_sec=_int("DEVICEON_TIMEOUT_SEC", 30),
            toolsets=toolsets,
            confirm_ttl_sec=_int("DEVICEON_CONFIRM_TTL_SEC", 300),
            temp_plugin=os.environ.get("DEVICEON_TEMP_PLUGIN") or None,
            temp_sensor=os.environ.get("DEVICEON_TEMP_SENSOR") or None,
            protected_processes=frozenset(DEFAULT_PROTECTED_PROCESSES | extra_protected),
        )


# OS-critical processes and the DeviceOn agent itself. Killing any of these would
# crash the device or cut it off from DeviceOn, so the server refuses outright.
DEFAULT_PROTECTED_PROCESSES = frozenset(
    {
        # DeviceOn / WISE agent
        "cagent.exe", "cagent", "saagent", "wiseagent", "wiseagent.exe",
        # Windows
        "system", "system idle process", "idle", "smss.exe", "csrss.exe", "wininit.exe",
        "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe", "explorer.exe",
        "dwm.exe", "registry", "memory compression",
        # Linux
        "systemd", "init", "kthreadd", "sshd", "dbus-daemon", "systemd-journald",
        "systemd-logind", "networkmanager",
    }
)

PROTECTED_PIDS = frozenset({0, 1, 2, 4})
