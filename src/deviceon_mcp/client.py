"""Thin async client for the DeviceOn Portal REST API (/rmm/v1/...).

Only the endpoints the PoC needs are wrapped. Request/response shapes follow the
apidoc comments in WebApp (DeviceAPIDoc, DataAPIDoc, ProcessCtrlAPIDOC).
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import Settings

# DataMgmt parses beginTs/endTs with "yyyy-MM-dd HH:mm:ss.SSS" in UTC.
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


class DeviceOnError(Exception):
    def __init__(self, status: int, message: str, body: Any = None):
        super().__init__(f"DeviceOn API error {status}: {message}")
        self.status = status
        self.body = body


def format_ts(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime(_TS_FORMAT) + f".{dt.microsecond // 1000:03d}"


class DeviceOnClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        headers = {"Accept": "application/json"}
        if settings.token:
            headers["Authorization"] = f"Bearer {settings.token}"
        else:
            raw = f"{settings.username}:{settings.password}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        self._verify = settings.verify_tls
        self._http = httpx.AsyncClient(
            base_url=settings.base_url,
            headers=headers,
            verify=settings.verify_tls,
            timeout=settings.timeout_sec,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as ex:
            raise DeviceOnError(0, f"{method} {path} failed: {ex}") from ex
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise DeviceOnError(resp.status_code, f"{method} {path}", body)
        if not resp.content:
            return None
        return resp.json()

    # ---- devices -------------------------------------------------------

    async def list_devices(
        self,
        like: str | None = None,
        like_field: str = "name",
        connected: bool | None = None,
        page_size: int = 20,
        page_no: int = 1,
    ) -> dict:
        """GET /v1/devicegroups/devices (DeviceGroupMgmt, 'Get Devices/AllGroup')."""
        params: dict[str, Any] = {"pageSize": page_size, "no": page_no}
        if like:
            params["like"] = like
            params["likeField"] = like_field
        if connected is not None:
            params["connected"] = str(connected).lower()
        return await self._request("GET", "/v1/devicegroups/devices", params=params)

    async def get_device(self, did: int) -> dict:
        """GET /v1/devices/{did}; returns the single device object."""
        data = await self._request("GET", f"/v1/devices/{did}")
        devices = (data or {}).get("devices") or []
        if not devices:
            raise DeviceOnError(404, f"device {did} not found")
        return devices[0]

    # ---- data ----------------------------------------------------------

    async def get_hist_data(
        self,
        did: int,
        agent_id: str,
        plugin: str,
        sensor_id: str,
        begin: datetime,
        end: datetime,
        amount: int = 10000,
        order: str = "asc",
    ) -> list[dict]:
        """GET /v1/data/devices/{did}/histdata -> list of {sensorId, v, ts, opTS}."""
        params = {
            "agentId": agent_id,
            "plugin": plugin,
            "sensorId": sensor_id,
            "beginTs": format_ts(begin),
            "endTs": format_ts(end),
            "amount": amount,
            "order": order,
        }
        data = await self._request("GET", f"/v1/data/devices/{did}/histdata", params=params)
        items = (data or {}).get("itemList") or []
        # When DataMgmt serves from its cache it wraps the cached array once more
        # (resultAry.put(cacheData)), so itemList may arrive as [[...]]. Flatten it.
        flat: list[dict] = []
        for item in items:
            if isinstance(item, list):
                flat.extend(i for i in item if isinstance(i, dict))
            elif isinstance(item, dict):
                flat.append(item)
        return flat

    async def get_latest_data(
        self,
        did: int,
        agent_id: str,
        plugin: str,
        sensor_id: str | None = None,
        source: str | None = None,
    ) -> dict:
        """GET /v1/data/devices/{did}/latestdata -> {"connected": bool, "<plugin>": {...}}.

        Without sensorId DataMgmt reads plugin_live_data first (written by
        intermittent reports, commCmd 534) and falls back to plugin_latest_raw_data
        (periodic auto-report). source="autoreport" reads only the periodic data.
        """
        params = {"agentId": agent_id, "plugin": plugin}
        if sensor_id:
            params["sensorId"] = sensor_id
        if source:
            params["source"] = source
        return await self._request("GET", f"/v1/data/devices/{did}/latestdata", params=params) or {}

    async def start_intermittent_report(
        self, agent_id: str, plugin: str, interval_sec: int, timeout_sec: int
    ) -> dict:
        """PUT /v1/devicectrl/intermittent_report -> {"result": true}.

        Asks the agent to upload the plugin's FULL data every interval_sec for
        timeout_sec (DeviceCtrl sends commCmd 533 with autoUploadIntervalMs =
        interval*1000). Both values must be JSON integers, in seconds.
        Requires the GetSensor permission and a connected device.
        """
        body = {"agentid": agent_id, "plugin": plugin, "interval": int(interval_sec), "timeout": int(timeout_sec)}
        return await self._request("PUT", "/v1/devicectrl/intermittent_report", json=body) or {}

    # ---- processes -----------------------------------------------------

    async def get_process_snapshot(self, did: int, agent_id: str) -> dict:
        """Latest ProcessMonitor data, preferring the intermittent-report (live) copy.

        Deliberately NOT GET /v1/processes/devices/{did}: that endpoint reads only the
        periodic auto-report row (which usually lacks the process list) and is cached
        server-side for a whole report interval.
        """
        data = await self.get_latest_data(did, agent_id, "ProcessMonitor")
        return (data or {}).get("ProcessMonitor") or {}

    async def kill_processes(self, did: int, pids: list[int]) -> dict:
        """PUT /v1/processes {"did", "action": "kill", "pids": [...]} -> {"result": bool}."""
        body = {"did": did, "action": "kill", "pids": pids}
        return await self._request("PUT", "/v1/processes", json=body) or {}

    async def launch_process(self, agent_id: str, cmd: str, arg: str, hidden: bool) -> dict:
        """POST /v1/processes (ProcessCtrl.runProcess, commCmd 171) -> {"result": bool}.

        Runs an executable on the device in the logged-on user's session. No output comes
        back; result=false also covers agent-side failures such as arg longer than ~260 chars.
        """
        body = {"agentId": agent_id, "cmd": cmd, "arg": arg, "hidden": hidden}
        return await self._request("POST", "/v1/processes", json=body) or {}

    # ---- power ---------------------------------------------------------

    async def get_power(self, did: int) -> dict:
        """GET /v1/power/devices/{did} -> {"agentId", "functionList": "wol,shutdown,restart", "did"}."""
        data = await self._request("GET", f"/v1/power/devices/{did}")
        return ((data or {}).get("devices") or [{}])[0]

    async def power_device(self, did: int, action: str) -> dict:
        """PUT /v1/power/device {"did", "action": sleep|hibernate|shutdown|restart|start}."""
        return await self._request("PUT", "/v1/power/device", json={"did": did, "action": action}) or {}

    # ---- screenshot ----------------------------------------------------

    async def get_screenshot(self, did: int) -> dict:
        """GET /v1/screenshot/devices/{did}?resType=base64 -> {"picBase64": str, "login": bool|None}."""
        data = await self._request("GET", f"/v1/screenshot/devices/{did}", params={"resType": "base64"})
        return (data or {}).get("result") or {}

    # ---- set data ------------------------------------------------------

    async def set_data(self, agent_id: str, plugin: str, entries: list[dict]) -> dict:
        """PUT /v1/devicectrl/data; entries are SenML items like {"n": "/Coils/LED0", "bv": true}.

        Returns {"items": [{"sensorPath", "statusCode", "sv", "ts"}]}.
        """
        body = {"agentId": agent_id, "plugin": plugin, "sensorIds": entries}
        return await self._request("PUT", "/v1/devicectrl/data", json=body) or {}

    # ---- KVM -----------------------------------------------------------

    async def start_kvm(self, agent_id: str, mode: int, repeater_id: int | None, force_restart_vnc: bool) -> dict:
        """POST /v1/kvm (KVMMgmt; keys matched case-insensitively) -> {"KVMmode", "port", "IP"}.

        mode 1 = P2P, 3 = repeater (needs repeaterid).
        """
        body: dict[str, Any] = {"agentid": agent_id, "mode": mode, "forceRestartWinVNC": 1 if force_restart_vnc else 0}
        if repeater_id is not None:
            body["repeaterid"] = repeater_id
        return await self._request("POST", "/v1/kvm", json=body) or {}

    # ---- protection / recovery ----------------------------------------

    async def get_protection(self, did: int) -> dict:
        """GET /v1/protection/devices/{did} -> device dict with installed/activated/expired/functionList."""
        data = await self._request("GET", f"/v1/protection/devices/{did}")
        return ((data or {}).get("devices") or [{}])[0]

    async def protection_device(self, did: int, action: str) -> dict:
        """PUT /v1/protection/device {"did", "action": install|update|protect|unprotect|activate}."""
        return await self._request("PUT", "/v1/protection/device", json={"did": did, "action": action}) or {}

    async def get_recovery(self, did: int) -> dict:
        """GET /v1/recovery/devices/{did} -> device dict with installed/activated/asz/functionList."""
        data = await self._request("GET", f"/v1/recovery/devices/{did}")
        return ((data or {}).get("devices") or [{}])[0]

    async def recovery_device(self, did: int, action: str, remote: bool | None = None, asz: int | None = None) -> dict:
        """PUT /v1/recovery/device {"did", "action": install|update|backup|recovery|activate, "remote"?, "asz"?}."""
        body: dict[str, Any] = {"did": did, "action": action}
        if remote is not None:
            body["remote"] = remote
        if asz is not None:
            body["asz"] = asz  # RecoveryMgmt reads it with getLong
        return await self._request("PUT", "/v1/recovery/device", json=body) or {}

    async def has_remote_backup(self, agent_id: str) -> bool:
        """GET /v1/recovery/devices/remote/backup/{agentId} -> {"result": bool}."""
        data = await self._request("GET", f"/v1/recovery/devices/remote/backup/{agent_id}")
        return bool((data or {}).get("result"))

    # ---- device log (Syslog plugin) -------------------------------------

    async def devlog_event_types(self, agent_id: str) -> list[str]:
        """GET /v1/devlog?agentId= -> {"eventTypes": ["Application", "System", ...]}."""
        data = await self._request("GET", "/v1/devlog", params={"agentId": agent_id})
        return list((data or {}).get("eventTypes") or [])

    async def request_devlog(self, agent_id: str, event: str, since_ms: int, until_ms: int) -> dict:
        """POST /v1/devlog/requests: the agent uploads the event log range to the portal's remote storage."""
        body = {"agentId": agent_id, "event": event, "st": since_ms, "et": until_ms}
        return await self._request("POST", "/v1/devlog/requests", json=body) or {}

    async def list_devlog_requests(self, agent_id: str, page_size: int = 5) -> list[dict]:
        """GET /v1/devlog/requests -> newest first: {id, event, filename, requestTime, responseTime, error}."""
        data = await self._request("GET", "/v1/devlog/requests", params={"agentId": agent_id, "pageSize": page_size})
        return list((data or {}).get("data") or [])

    async def download_devlog(self, request_id: int) -> bytes:
        """GET /v1/devlog/requests/{id}: either the file itself or JSON {"location": url}."""
        try:
            resp = await self._http.get(f"/v1/devlog/requests/{request_id}")
        except httpx.HTTPError as ex:
            raise DeviceOnError(0, f"devlog download failed: {ex}") from ex
        if resp.status_code >= 400:
            raise DeviceOnError(resp.status_code, f"GET /v1/devlog/requests/{request_id}", resp.text[:500])
        if "json" in (resp.headers.get("content-type") or ""):
            loc = (resp.json() or {}).get("location")
            if not loc:
                raise DeviceOnError(resp.status_code, "devlog download returned no location", resp.text[:500])
            try:
                async with httpx.AsyncClient(timeout=self._http.timeout, verify=self._verify) as h:
                    r2 = await h.get(loc)
            except httpx.HTTPError as ex:
                raise DeviceOnError(0, f"devlog file download failed: {ex}") from ex
            if r2.status_code >= 400:
                raise DeviceOnError(r2.status_code, "devlog file download", r2.text[:500])
            return r2.content
        return resp.content
