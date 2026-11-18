"""In-process fake of the DeviceOn Portal REST API for tests.

Simulates one device whose CPU spikes to ~92% for 60 s every 180 s, caused by a
'python3' process (pid 4321). Responses follow the shapes in the WebApp apidoc and
the storage behaviour verified in the backend source:

- Periodic auto-report (every 60 s) carries only "System Monitor Info" and lands in
  plugin_latest_raw_data (GET /processes, latestdata?source=autoreport).
- PUT /devicectrl/intermittent_report makes the agent upload the FULL plugin every
  `interval` s for `timeout` s into plugin_live_data (latestdata without sensorId).
- plugin_live_data keeps the last upload forever: it starts with a stale snapshot
  from 3 hours ago, in which the stress process shows 0% CPU.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx

DID = 7
AGENT_ID = "00000001-0000-0000-0000-000BAB578433"
STEP_MS = 5_000
PERIODIC_MS = 60_000
PERIOD_MS = 180_000
HIGH_MS = 60_000
STRESS_PID = 4321
STRESS_NAME = "python3"


def _e(name, value):
    if isinstance(value, bool):
        return {"n": name, "bv": value}
    if isinstance(value, str):
        return {"n": name, "sv": value}
    return {"n": name, "v": value}


class FakeDeviceOn:
    def __init__(self, start_ms: int = 1_800_000_000_000):
        self.start = start_ms
        self.now = start_ms
        self.killed: list[int] = []
        self.stress_pid = STRESS_PID
        self.stress_name = STRESS_NAME
        self.requests: list[httpx.Request] = []
        # intermittent report state / knobs
        self.live_until = 0
        self.live_interval_ms = 2_000
        self.intermittent_calls: list[dict] = []
        self.fail_intermittent = False   # portal rejects the request (e.g. 403 no GetSensor)
        self.agent_ignores_live = False  # request accepted but agent never uploads
        self.ignore_kill = False         # kill acknowledged but process keeps running
        self.connected = True

    # -- simulated signal -----------------------------------------------
    def alive(self) -> bool:
        return self.stress_pid not in self.killed

    def in_peak(self, t_ms: int) -> bool:
        return self.alive() and (t_ms % PERIOD_MS) < HIGH_MS

    def system_cpu(self, t_ms: int) -> float:
        jitter = (t_ms // STEP_MS) % 3  # deterministic small noise
        return (90.0 + jitter) if self.in_peak(t_ms) else (7.0 + jitter)

    # -- clock helpers for Deps -----------------------------------------
    def now_ms(self) -> int:
        return self.now

    async def sleep(self, sec: float) -> None:
        self.now += int(sec * 1000)

    # -- HTTP -------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if not req.headers.get("Authorization", "").startswith(("Basic ", "Bearer ")):
            return httpx.Response(403, json={"error": "no auth"})
        path = req.url.path
        q = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
        if req.method == "GET" and path == "/rmm/v1/devicegroups/devices":
            return self._devices(q)
        if req.method == "GET" and path == f"/rmm/v1/devices/{DID}":
            return httpx.Response(200, json={"total": 1, "devices": [self._device()]})
        if req.method == "GET" and path.startswith("/rmm/v1/devices/"):
            return httpx.Response(404, json={"errorCode": 1})
        if req.method == "GET" and path == f"/rmm/v1/data/devices/{DID}/histdata":
            return self._histdata(q)
        if req.method == "GET" and path == f"/rmm/v1/data/devices/{DID}/latestdata":
            return self._latest(q)
        if req.method == "GET" and path == f"/rmm/v1/processes/devices/{DID}":
            # Real endpoint: periodic raw row only -> no process list
            return httpx.Response(200, json={"ProcessMonitor": self._periodic_pm()})
        if req.method == "PUT" and path == "/rmm/v1/devicectrl/intermittent_report":
            return self._intermittent(json.loads(req.content))
        if req.method == "PUT" and path == "/rmm/v1/processes":
            body = json.loads(req.content)
            assert body["action"] == "kill" and body["did"] == DID
            if not self.ignore_kill:
                self.killed.extend(body["pids"])
            return httpx.Response(200, json={"result": True})
        return httpx.Response(404, json={"error": f"unhandled {req.method} {path}"})

    def _device(self) -> dict:
        return {
            "did": DID, "name": "Line-B-AOI-03", "agentId": AGENT_ID, "connected": self.connected,
            "ostype": "Ubuntu 22.04", "localip": "10.0.0.31", "cpuname": "Intel Core i5",
            "devicegroups": [{"gid": 1, "name": "Line-B"}],
            "plugins": [{"plugin": p, "normal": True} for p in ("ProcessMonitor", "SUSIControl", "terminal")],
        }

    def _devices(self, q: dict) -> httpx.Response:
        devs = [self._device()]
        like = q.get("like")
        if like:
            devs = [d for d in devs if like.lower() in d["name"].lower()]
        return httpx.Response(200, json={"total": len(devs), "devices": devs})

    def _histdata(self, q: dict) -> httpx.Response:
        fmt = "%Y-%m-%d %H:%M:%S.%f"
        begin = int(datetime.strptime(q["beginTs"], fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        end = int(datetime.strptime(q["endTs"], fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        assert q["agentId"] == AGENT_ID and q["plugin"] == "ProcessMonitor"
        items = []
        t = begin - begin % STEP_MS + STEP_MS
        while t <= end:
            items.append({"sensorId": q["sensorId"], "v": self.system_cpu(t), "ts": t, "opTS": t - 3})
            t += STEP_MS
        # Mimic DataMgmt's cache path which nests the array: itemList = [[...]]
        return httpx.Response(200, json={"connected": True, "total": 1, "itemList": [items]})

    def _intermittent(self, body: dict) -> httpx.Response:
        if self.fail_intermittent:
            return httpx.Response(403, json={"errorCode": 1104, "description": "permission denied"})
        # DeviceCtrl rejects non-integer interval/timeout
        assert isinstance(body["interval"], int) and isinstance(body["timeout"], int), body
        assert body["agentid"] == AGENT_ID and body["plugin"] == "ProcessMonitor", body
        if not self.connected:
            return httpx.Response(400, json={"errorCode": 1, "description": "device offline"})
        self.intermittent_calls.append(body)
        if not self.agent_ignores_live:
            self.live_interval_ms = body["interval"] * 1000
            self.live_until = self.now + body["timeout"] * 1000
        return httpx.Response(200, json={"result": True})

    def _latest(self, q: dict) -> httpx.Response:
        plugin = q["plugin"]
        if plugin == "ProcessMonitor":
            if q.get("source") == "autoreport":
                body = self._periodic_pm()
            else:
                body = self._live_pm()
        elif plugin == "SUSIControl":
            body = {"handler": "SUSIControl", "Hardware Monitor": {"bn": "Hardware Monitor", "Temperature": {
                "bn": "Temperature", "e": [_e("CPU", 78.0 if self.in_peak(self.now) else 48.0), _e("SYS", 40.0)]}}}
        else:
            return httpx.Response(404, json={"errorCode": 1})
        return httpx.Response(200, json={"connected": True, plugin: body})

    # -- ProcessMonitor payloads -----------------------------------------
    def _system_info(self, t_ms: int) -> dict:
        return {"bn": "System Monitor Info",
                "e": [_e("CPU Usage", self.system_cpu(t_ms)), _e("totalPhysMemKB", 8_000_000),
                      _e("availPhysMemKB", 2_000_000), _e("usagePhysMem", 75)]}

    def _periodic_pm(self) -> dict:
        ts = self.now - self.now % PERIODIC_MS
        return {"handler": "ProcessMonitor", "agentId": AGENT_ID, "dataFlow": 1, "seq": 1,
                "System Monitor Info": self._system_info(ts), "ts": ts, "opTS": ts}

    def _full_pm(self, ts: int, stress_cpu: float | None = None) -> dict:
        peak = self.in_peak(ts)

        def proc(pid, name, owner, cpu, mem=10_000):
            return {"bn": f"{pid}-{name}", "e": [_e("Name", name), _e("PID", pid), _e("Owner", owner),
                                                  _e("CPU Usage", cpu), _e("Mem Usage", mem), _e("IsActive", True)]}

        procs = [proc(100, "cagent", "root", 1), proc(1, "systemd", "root", 0),
                 proc(200, "chrome", "op", 3), proc(300, "chrome", "op", 2)]
        if self.alive():
            cpu = stress_cpu if stress_cpu is not None else (85 if peak else 0.3)
            procs.append(proc(self.stress_pid, self.stress_name, "op", cpu))
        return {"handler": "ProcessMonitor", "agentId": AGENT_ID,
                "Process Monitor Info": procs, "System Monitor Info": self._system_info(ts), "ts": ts, "opTS": ts}

    def _live_pm(self) -> dict:
        if self.now < self.live_until:
            return self._full_pm(self.now - self.now % self.live_interval_ms)
        if self.live_until:  # last upload of a finished intermittent report stays in the table
            end = self.live_until - self.live_until % self.live_interval_ms
            return self._full_pm(end)
        # stale leftover from someone's portal session 3 hours ago
        return self._full_pm(self.start - 3 * 3600_000, stress_cpu=0)
