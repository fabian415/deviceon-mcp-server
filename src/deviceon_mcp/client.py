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
