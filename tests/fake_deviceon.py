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

import base64
import json
import re
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
# memory scenario: a scheduled job that grows to 4 GB, holds, exits; new pid every run
LEAK_NAME = "mem_leak.exe"
LEAK_PID_BASE = 5000
LEAK_PEAK_MB = 4096
LEAK_GROW_MS = 60_000
LEAK_HOLD_MS = 30_000


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
        self.scenario = "cpu"            # "cpu": python3 CPU spikes; "memory": scheduled mem_leak.exe
        self.hide_leak = False           # memory scenario: agent does not list mem_leak (e.g. a service)
        # control toolset state (shapes from PowerAPIDOC, ScreenshotAPIDOC, KVMAPIDOC, Protection/RecoveryAPIDOC)
        self.power_functions = "wol,shutdown,restart"   # what DESKTOP-MT3CC6E reports
        self.power_calls: list[dict] = []
        self.screenshot_login: bool | None = True
        self.screenshot_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        self.set_data_calls: list[dict] = []
        self.modbus = {"/Coils/LED0": False, "/Discrete Inputs/Input0": True, "/Holding Registers/Data0": 5}
        self.kvm_calls: list[dict] = []
        self.protection = {"installed": True, "activated": True, "expired": False, "status": "Connected",
                           "lock": "None", "functionList": "protect,unprotect,remoteinstall,remoteupdate,remoteactivate"}
        self.recovery = {"installed": True, "activated": True, "expired": False, "asz": True, "status": "Connected",
                         "lock": "None", "functionList": "backup,recovery,remoteinstall,remoteupdate,remoteactivate"}
        self.remote_backup = False
        self.protection_calls: list[dict] = []
        self.recovery_calls: list[dict] = []
        # remote execution: Launch Remote Process + device log
        self.ostype = "Windows 10 Enterprise"
        self.launches: list[dict] = []
        self.launch_result = True          # False: agent refuses (e.g. nobody logged on)
        self.devlog_error = ""             # e.g. "500:Copyfile fail : Syntax or usage error (&d)"
        self.devlog_requests: list[dict] = []

    # -- simulated signal -----------------------------------------------
    def alive(self) -> bool:
        return self.stress_pid not in self.killed

    def in_peak(self, t_ms: int) -> bool:
        return self.scenario == "cpu" and self.alive() and (t_ms % PERIOD_MS) < HIGH_MS

    def leak(self, t_ms: int) -> tuple[int, float] | None:
        """(pid, MB) of the running mem_leak.exe at t, or None between runs."""
        if self.scenario != "memory":
            return None
        phase = t_ms % PERIOD_MS
        if phase >= LEAK_GROW_MS + LEAK_HOLD_MS:
            return None
        mb = LEAK_PEAK_MB * min(1.0, phase / LEAK_GROW_MS)
        return LEAK_PID_BASE + t_ms // PERIOD_MS % 1000, mb

    def mem_used_mb(self, t_ms: int) -> float:
        jitter = (t_ms // STEP_MS) % 3 * 20
        lk = self.leak(t_ms)
        return 6144 + jitter + (lk[1] if lk else 0)

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
        control = self._control(req, path, q)
        if control is not None:
            return control
        return httpx.Response(404, json={"error": f"unhandled {req.method} {path}"})

    def _control(self, req: httpx.Request, path: str, q: dict) -> httpx.Response | None:
        body = json.loads(req.content) if req.content else {}
        m = req.method
        if m == "GET" and path == f"/rmm/v1/power/devices/{DID}":
            return httpx.Response(200, json={"total": 1, "devices": [
                {"agentId": AGENT_ID, "functionList": self.power_functions, "did": DID}]})
        if m == "PUT" and path == "/rmm/v1/power/device":
            assert isinstance(body["did"], int), body
            self.power_calls.append(body)
            return httpx.Response(200, json={"result": True})
        if m == "GET" and path == f"/rmm/v1/screenshot/devices/{DID}":
            assert q.get("resType") == "base64", q
            if self.screenshot_login is False:
                return httpx.Response(200, json={"result": {"login": False}})
            return httpx.Response(200, json={"result": {
                "picBase64": base64.b64encode(self.screenshot_bytes).decode(), "login": True}})
        if m == "PUT" and path == "/rmm/v1/devicectrl/data":
            assert body["agentId"] == AGENT_ID, body
            self.set_data_calls.append(body)
            items = []
            for e in body["sensorIds"]:
                value = e.get("bv", e.get("v", e.get("sv")))
                if e["n"] in self.modbus:
                    self.modbus[e["n"]] = value
                items.append({"sv": "Success", "sensorPath": body["plugin"] + e["n"], "statusCode": 200, "ts": self.now})
            return httpx.Response(200, json={"items": items})
        if m == "POST" and path == "/rmm/v1/kvm":
            assert body["agentid"] == AGENT_ID and body["mode"] in (1, 3), body
            self.kvm_calls.append(body)
            return httpx.Response(200, json={"KVMmode": "default", "port": 6082, "IP": "kvm.deviceon.test"})
        for name, info, calls in (("protection", self.protection, self.protection_calls),
                                  ("recovery", self.recovery, self.recovery_calls)):
            if m == "GET" and path == f"/rmm/v1/{name}/devices/{DID}":
                return httpx.Response(200, json={"total": 1, "devices": [{**info, "agentId": AGENT_ID, "did": DID}]})
            if m == "PUT" and path == f"/rmm/v1/{name}/device":
                assert isinstance(body["did"], int) and isinstance(body.get("asz", 0), int), body
                calls.append(body)
                return httpx.Response(200, json={"result": True})
        if m == "GET" and path == f"/rmm/v1/recovery/devices/remote/backup/{AGENT_ID}":
            return httpx.Response(200, json={"result": self.remote_backup})
        if m == "GET" and path == "/rmm/v1/devlog":
            return httpx.Response(200, json={"eventTypes": ["Application", "System", "Windows PowerShell"]})
        if m == "POST" and path == "/rmm/v1/processes":
            assert body["agentId"] == AGENT_ID and isinstance(body["hidden"], bool), body
            self.launches.append(body)
            # the real agent rejects args longer than ~260 chars
            return httpx.Response(200, json={"result": self.launch_result and len(body["arg"]) <= 260})
        if m == "POST" and path == "/rmm/v1/devlog/requests":
            self.devlog_requests.append(body)
            return httpx.Response(200, json={"result": True})
        if m == "GET" and path == "/rmm/v1/devlog/requests":
            data = [{"id": i + 1, "event": r["event"], "requestTime": self.now, "responseTime": "2026-11-18T08:28:34Z",
                     "error": self.devlog_error} for i, r in enumerate(self.devlog_requests)][::-1]
            return httpx.Response(200, json={"total": len(data), "data": data})
        if m == "GET" and path.startswith("/rmm/v1/devlog/requests/"):
            return httpx.Response(200, content=b"line one\nline two\n", headers={"content-type": "application/octet-stream"})
        return None

    def _modbus_pm(self) -> dict:
        def group(name, asm, keys):
            return {"bn": name, **({"basm": asm} if asm else {}),
                    "e": [_e(k.rsplit("/", 1)[1], self.modbus[k]) for k in keys]}
        return {
            "handler": "Modbus_Handler",
            "Coils": group("Coils", "rw", ["/Coils/LED0"]),
            "Discrete Inputs": group("Discrete Inputs", "r", ["/Discrete Inputs/Input0"]),
            "Holding Registers": {"bn": "Holding Registers", "e": [
                {**_e("Data0", self.modbus["/Holding Registers/Data0"]), "asm": "rw"}]},
        }

    def _device(self) -> dict:
        plugins = ("ProcessMonitor", "SUSIControl", "terminal", "power_onoff", "screenshot", "remote_kvm",
                   "protection", "recovery", "Syslog", "Modbus_Handler")
        return {
            "did": DID, "name": "Line-B-AOI-03", "agentId": AGENT_ID, "connected": self.connected,
            "ostype": self.ostype, "localip": "10.0.0.31", "cpuname": "Intel Core i5",
            "devicegroups": [{"gid": 1, "name": "Line-B"}],
            "plugins": [{"plugin": p, "normal": True} for p in plugins],
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
            v = self.mem_usage_pct(t) if q["sensorId"].endswith("usagePhysMem") else self.system_cpu(t)
            items.append({"sensorId": q["sensorId"], "v": v, "ts": t, "opTS": t - 3})
            t += STEP_MS
        # Like DataMgmt: sort by `order` (desc unless "asc"), then keep the first `amount`.
        if q.get("order", "").lower() != "asc":
            items.reverse()
        items = items[: min(int(q.get("amount", 10_000)), 10_000)]
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
        elif plugin == "Modbus_Handler":
            body = self._modbus_pm()
        elif plugin == "SUSIControl":
            body = {"handler": "SUSIControl", "Hardware Monitor": {"bn": "Hardware Monitor", "Temperature": {
                "bn": "Temperature", "e": [_e("CPU", 78.0 if self.in_peak(self.now) else 48.0), _e("SYS", 40.0)]}}}
        else:
            return httpx.Response(404, json={"errorCode": 1})
        return httpx.Response(200, json={"connected": True, plugin: body})

    # -- ProcessMonitor payloads -----------------------------------------
    def mem_usage_pct(self, t_ms: int) -> float:
        return self.mem_used_mb(t_ms) / 16384 * 100

    def _system_info(self, t_ms: int) -> dict:
        if self.scenario == "memory":  # 16 GB box
            total_kb = 16384 * 1024
            avail_kb = total_kb - self.mem_used_mb(t_ms) * 1024
            return {"bn": "System Monitor Info",
                    "e": [_e("CPU Usage", self.system_cpu(t_ms)), _e("totalPhysMemKB", total_kb),
                          _e("availPhysMemKB", avail_kb), _e("usagePhysMem", self.mem_usage_pct(t_ms))]}
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
        if self.scenario == "memory":
            procs.append(proc(400, "explorer.exe", "op", 1, mem=256_000))
            lk = self.leak(ts)
            if lk and not self.hide_leak and lk[0] not in self.killed:
                procs.append(proc(lk[0], LEAK_NAME, "op", 0, mem=lk[1] * 1024))
        elif self.alive():
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


class FakeTerminal:
    """Test double for terminal.TerminalClient that understands the scripts remote_exec builds.

    It decodes -EncodedCommand, recognises the stage / wait / event-log / system-wrapper
    scripts, and answers like the real agent would (base64 payload after __DOMCP_B64__).
    """

    B64 = "__DOMCP_B64__"

    def __init__(self, fake: FakeDeviceOn):
        self.fake = fake
        self.calls: list[str] = []          # decoded scripts / raw command lines
        self.staged: dict[str, str] = {}    # run_id -> .ps1 content
        self.system_output = "DESKTOP-TEST\r\n中文"
        self.user_output = "user=desktop-test\\op session=1"
        self.events: list[dict] = [{"time": "2026-11-18T16:00:00+08:00", "level": "Error", "id": 7031,
                                    "source": "Service Control Manager", "message": "The X service terminated."}]
        self.eventlog_error: str | None = None
        self.fail = False

    @classmethod
    def _emit(cls, text: str) -> str:
        return cls.B64 + base64.b64encode(text.encode("utf-8")).decode()

    async def run(self, agent_id, cmdline, timeout_sec=60, windows=True):
        from deviceon_mcp.terminal import TerminalError, TerminalResult
        if self.fail:
            raise TerminalError("terminal connection failed: refused")
        assert agent_id == AGENT_ID
        assert len(cmdline) <= 7_500, "websocket message would exceed the server's ~8 KB limit"
        script = cmdline
        if "-EncodedCommand " in cmdline:
            script = base64.b64decode(cmdline.split("-EncodedCommand ", 1)[1]).decode("utf-16-le")
        self.calls.append(script)
        if "'staged'" in script:
            b64 = script.split("FromBase64String('", 1)[1].split("'", 1)[0]
            run_id = re.search(r"DeviceOnMCP\\(\w+)\.ps1", script).group(1)
            self.staged[run_id] = base64.b64decode(b64).decode("utf-8")
            out = "staged"
        elif "DEVICEON-MCP " in script and "Get-WinEvent" in script and "ProviderName='WSH'" in script:
            run_id = script.split("DEVICEON-MCP ", 1)[1].split("'", 1)[0]
            launched = any(run_id in l["arg"] for l in self.fake.launches)
            out = self._emit(self.user_output) if launched and self.fake.launch_result else "__DOMCP_NO_EVENT__"
        elif "Get-WinEvent -FilterHashtable $f" in script:
            if self.eventlog_error:
                out = self._emit("DOMCP_ERROR " + self.eventlog_error)
            else:
                events = self.events[0] if len(self.events) == 1 else self.events  # PS unwraps 1-element arrays
                out = self._emit(json.dumps({"matched": len(self.events), "scanned_cap": 2000, "events": events}))
        elif script.startswith("$ProgressPreference") and "$o = try" in script:
            out = self._emit(self.system_output)
        else:  # plain cmd line (cmd shell, del ...)
            out = self.system_output if not cmdline.startswith("del ") else ""
        return TerminalResult(out, True, 0.5)
