# DeviceOn MCP Server（PoC）

讓 AI Agent 透過 MCP 呼叫 DeviceOn Portal REST API：偵測裝置的週期性 CPU 異常、找出造成異常的 process，並在使用者同意後結束它。

```
AI Agent (OpenClaw)  ──MCP──▶  DeviceOn MCP Server  ──REST /rmm/v1──▶  DeviceOn Portal  ──MQ──▶  Edge Agent
```

不需要修改 DeviceOn 後端，只使用既有的 API。

## 工具

| Toolset | 工具 | 類型 | 呼叫的 DeviceOn API |
|---|---|---|---|
| common | `list_devices`（`offline_only` 找已關機的裝置，附 `wakeOnLan` 模式與 `lastConnectedAt` 最後上線時間；`recent_first` 依最後上線時間新到舊排序） | 讀 | `GET /v1/devicegroups/devices` |
| diagnose | `analyze_metric_periodicity` | 讀 | `GET /v1/devices/{did}`、`GET /v1/data/devices/{did}/histdata` |
| diagnose | `get_current_metrics` | 讀 | `GET /v1/data/devices/{did}/latestdata?source=autoreport` |
| diagnose | `capture_top_processes`（`metric`: `cpu` / `memory`） | 讀 | `PUT /v1/devicectrl/intermittent_report` + `GET /v1/data/devices/{did}/latestdata`（取樣多次） |
| diagnose | `find_unresponsive_windows` | 讀 | 遠端執行固定的唯讀檢查（使用者 session，見[遠端執行](#遠端執行是怎麼做的)） |
| diagnose | `find_process_autostart` | 讀 | 遠端終端機執行固定的唯讀查詢：排程工作、服務、Run 機碼、啟動資料夾、執行中的 instance 與父 process |
| control | `request_kill_process` | 讀（只發 token） | `intermittent_report` + `latestdata`（取一份最新的 process 清單）→ 確認後 `PUT /v1/processes`（`action: kill`） |
| control | `get_device_capabilities` | 讀 | `GET /v1/devices/{did}`、`/v1/power/devices/{did}`、`/v1/protection/…`、`/v1/recovery/…`、`/v1/devlog` |
| control | `take_screenshot` | 讀（回傳圖片） | `GET /v1/screenshot/devices/{did}?resType=base64` |
| control | `request_power_action` | 讀（只發 token） | `GET /v1/power/devices/{did}` → 確認後 `PUT /v1/power/device`；`start` 會先檢查 WOL 模式與代理裝置是否在線 |
| control | `find_wol_relay_candidates` | 讀 | `GET /v1/devicegroups/devices?connected=true`，再用終端機問候選裝置自己的子網路（`Get-NetIPAddress`） |
| control | `request_configure_wol` | 讀（只發 token） | 確認後 `PATCH /v1/devices/wol`（需要 `EditDevice` 權限） |
| control | `wait_for_device_online` | 讀 | 輪詢 `GET /v1/devices/{did}` 直到上線 |
| control | `request_disable_autostart` | 讀（只發 token） | 終端機讀目前狀態 → 確認後 `Disable-ScheduledTask` 或 `Set-Service -StartupType Disabled` |
| control | `request_set_data` | 讀（只發 token） | `latestdata`（讀目前值與 asm）→ 確認後 `PUT /v1/devicectrl/data` |
| control | `request_kvm_session` | 讀（只發 token） | 確認後 `POST /v1/kvm`，回傳連線資訊給**人**（只能用 Portal 的瀏覽器 noVNC 開，不支援 UltraVNC） |
| control | `request_protection_action` | 讀（只發 token） | `GET /v1/protection/devices/{did}` → 確認後 `PUT /v1/protection/device` |
| control | `request_recovery_action` | 讀（只發 token） | `GET /v1/recovery/devices/{did}` → 確認後 `PUT /v1/recovery/device` |
| logs | `fetch_device_log` | 讀 | 預設：遠端終端機執行固定的 `Get-WinEvent` 查詢；`source=devlog`：`/v1/devlog/requests` |
| logs | `analyze_last_shutdown` | 讀 | 終端機執行固定的唯讀查詢（關機相關 System 事件、Application 警告／錯誤、目前記憶體前幾名）+ `histdata`（離線前的記憶體／CPU） |
| remote | `request_run_command` | 讀（只發 token） | 確認後經遠端終端機（SYSTEM）或 Launch Remote Process（使用者） |
| （自動） | `confirm_action` | **寫（破壞性）** | 執行任何 `request_*` 準備好的動作（包括 kill） |

- `diagnose` 是**純唯讀**；所有會改變裝置的動作（包括 kill）都在 `control`／`remote`，一律經過 `confirm_action`。只開 `common,diagnose` 的部署不能 kill。
- `confirm_action` 只在開啟了 `control` 或 `remote` 這類會改變裝置狀態的 toolset 時才會出現。
- **延後載入**：Claude Code 和 OpenClaw 預設只先給模型 tool 名稱，用到時才載入完整定義，所以 tool 變多也不會每輪吃掉大量 token。`list_devices`、`get_device_capabilities`、`confirm_action` 是幾乎每個任務都會用到的入口，標了 `_meta["anthropic/alwaysLoad"]`，在 Claude Code 會預先載入、省一次搜尋。toolset 的用途是**讓管理者決定這個環境能做什麼**，不是為了省 token。新增 tool 時，名稱維持 `request_`／`get_`／`list_` 等固定開頭，說明第一句用英文寫清楚用途關鍵字（OpenClaw 的搜尋是英文關鍵字比對）。
- **刻意不做群組操作**（`/power/group`、`/protection/group` 等）：一次確認不應該影響一整群機器。
- **KVM 只能用瀏覽器開**：`request_kvm_session` 回傳的 port 80 是給 Portal 瀏覽器版 noVNC 用的 web port，不是原生 VNC（RFB）port，**UltraVNC 等原生 VNC viewer 不支援**。使用者要到 DeviceOn Portal 該裝置的 KVM 頁面開啟。
- **KVM 檔案傳輸沒有實作**：DeviceOn 用瀏覽器端的 WebRTC 傳檔，MCP server 無法扮演瀏覽器。需要時可用 `request_run_command` 讓裝置自己下載。

### process 清單是怎麼拿到的

這段已在實機（Windows agent）上驗證過，修改相關程式前請先讀：

| 資料 | agent 指令 | 寫入的資料表 | 讀取的 API |
|---|---|---|---|
| 定期回報：**只有** `System Monitor Info`（CPU、記憶體），沒有 process 清單 | autoreport | `plugin_latest_raw_data` | `GET /v1/processes/devices/{did}`、`latestdata?source=autoreport` |
| intermittent report：**完整** ProcessMonitor 資料 | 533 開始 → agent 回 534 | `plugin_live_data` | `latestdata`（不帶 `sensorId`） |

- 所以抓 process 的工具會先呼叫 `intermittent_report`（`interval` 和 `timeout` 單位是秒，必須是整數），要求 agent 在一段時間內每隔幾秒上傳完整資料，再從 `latestdata` 讀取。Portal 網頁的即時頁面也是這樣做的。
- **不使用 `GET /v1/processes/devices/{did}`**：它只讀定期回報那張表（通常沒有 process 清單），而且在 Portal 端會依裝置回報 interval 快取。
- `plugin_live_data` 會一直保留**最後一次** intermittent 的資料，可能是好幾小時前有人開網頁時留下的。工具只採用伺服器時間戳**比觸發前更新**、而且**含有 process 清單**的快照，其餘一律略過。kill 前的確認和 kill 後的驗證也遵守同樣的規則，拿不到新資料時寧可不 kill（`aborted_no_fresh_data`）。

### 安全設計

- **兩段式 kill**：`confirm_action` 只接受 `request_kill_process` 發出的 token，不接受 pid。Agent 無法跳過「詢問使用者」這一步。token 只能用一次，預設 5 分鐘後失效，只存在記憶體中。
- **PID 重用保護**：確認 kill 前會重新讀取 process 清單；如果 pid 已經屬於其他程式名稱，就中止並回報 `aborted_pid_reused`。
- **保護清單**：系統關鍵 process 和 DeviceOn agent 本身（`cagent`、`systemd`、`lsass.exe` 等，見 [config.py](src/deviceon_mcp/config.py)）一律拒絕。可以用 `DEVICEON_PROTECTED_PROCESSES` 擴充。
- **稽核記錄**：每次 kill 的申請、執行、中止都會寫進 `deviceon_mcp.audit` logger（輸出到 stderr）。DeviceOn 端也會留下 `SetKillPrc` 操作事件。
- **所有會改變裝置的動作都是兩段式**：`request_*` 只做檢查，回傳摘要、警示和 token（工具標成 readOnly），`confirm_action` 才真的執行。檢查內容依工具而定：開關機比對裝置支援的動作和在線狀態；寫入資料拒絕唯讀或不存在的感測器並列出「目前值 → 新值」；保護／還原檢查軟體是否已安裝、啟用，遠端還原前確認遠端備份存在。
- **LLM 自己寫的腳本（`remote` toolset）**：要同時設定 `DEVICEON_TOOLSETS` 含 `remote` **和** `DEVICEON_ALLOW_REMOTE_COMMAND=true` 才會開啟。摘要會附上完整腳本；拒絕 `-EncodedCommand`（看不出內容）；對刪除、格式化、關機、停服務、kill、改登錄檔、改帳號、下載、動態執行、改安全設定、提到受保護的 process 等寫法加上警示。腳本上限 2500 字元。
- **YOLO 模式（`DEVICEON_AUTO_CONFIRM`，預設關閉）**：列出的動作（逗號分隔，或 `all`）在 `request_*` 就直接執行並回傳結果（`auto_confirmed: true`），不發 token、不用 `confirm_action`，適合反覆調整腳本的開發／測試情境。動作名稱：`run_command`、`kill_process`、`power`、`set_data`、`kvm`、`protection`、`recovery`、`wol_config`、`disable_autostart`。
  - 仍然有效的檢查：保護清單、PID 重用、拒絕 `-EncodedCommand`、腳本長度、在線狀態等 request 階段的檢查都照做；稽核記錄會多一行 `action auto-confirmed (YOLO)`。
  - **命中風險樣式的腳本仍然要確認**：`run_command` 在 YOLO 下只自動執行沒有風險警示的腳本（例如查詢類）；有刪除、停服務、kill 等警示的會照常回傳 token 和 `auto_confirm_skipped`。
  - 寫錯名稱或該動作所屬的 toolset 沒開，server 會拒絕啟動。開啟後對應的 `request_*` 工具會改標成 destructive，server instructions 也會告訴 Agent 不用先詢問。
  - 在 Claude Code，`request_*` 已在 `allow`，所以 YOLO 的動作完全不會跳出視窗；`confirm_action` 保留在 `ask`，只有被判定為風險的請求才會用到。建議只在個人環境用 `"DEVICEON_AUTO_CONFIRM": "run_command"`，不要寫進共用的 `.mcp.json`，也不要和 HTTP 模式一起用。
- **防 prompt injection**：process 名稱、視窗標題、log、截圖、指令輸出都來自裝置，回傳時都標註為不可信資料；server 的 instructions 也要求 Agent 不要照著裝置資料裡的文字行動。
- **權限**：使用 DeviceOn 帳號呼叫 API，沿用 DeviceOn 原本的角色和裝置群組權限。建議建立專用的服務帳號，只授予 `GetData`、`GetSensor`（`intermittent_report` 需要）、`GetProcess`、`EditProcess` 權限，以及目標裝置群組。要用 `request_configure_wol` 時另外需要 `EditDevice`。

### 遠端執行是怎麼做的

已在實機（Windows 10 agent，2026-11）驗證。DeviceOn 有兩個能在裝置上執行東西的管道，各有限制，所以依「要用誰的身分執行」選擇：

| `run_as` | 管道 | 身分 | 輸出怎麼回來 | 速度 |
|---|---|---|---|---|
| `system`（預設） | 遠端終端機 websocket `wss://<host>/terminal/<basic>/<agentId>/<uuid>`（**沒有 `/rmm`**，網址取自 Portal 的 `WebShell.js`） | `NT AUTHORITY\SYSTEM`，session 0 | 直接回傳 | 約 1 秒 |
| `user` | ① 終端機把腳本寫到 `C:\ProgramData\DeviceOnMCP\<id>.ps1` ② `POST /v1/processes`（Launch Remote Process）用 `-File` 執行 ③ 腳本把輸出寫進 Application 事件記錄（`WScript.Shell.LogEvent`，來源 WSH，帶 `<id>`）④ 終端機讀回事件並刪除腳本 | 登入的使用者，session 1 | 經事件記錄 | 約 3 秒 |

- **為什麼需要 `user`**：`Process.Responding` 只看得到同一個桌面的視窗。實測同一個卡死的 `hang_app.exe`，SYSTEM 看到的是 `Responding=True`（誤判），使用者 session 看到的是 `False`。
- **實測到的限制**：
  - Launch Remote Process 的 `arg` 超過約 260 字元會失敗，Portal 只回 `{"result": false}`，不說原因；它也不會回傳輸出。所以只用它啟動已寫好的 `.ps1`。
  - 終端機的單一 websocket 訊息超過約 8 KB，伺服器會以 1009 斷線，所以命令列上限 7500 字元、腳本上限 2500 字元。
  - 終端機轉送的是 cmd.exe 的輸出（OEM 字碼頁），中文會變成 `?`。PowerShell 的輸出一律先轉成 UTF-8 再用 base64 傳回。
  - PowerShell 第一次載入模組時會在 stderr 印出 CLIXML 進度訊息，已用 `$ProgressPreference='SilentlyContinue'` 關掉，解析時也會濾掉。
- **DeviceOn 的 Device Log（`/v1/devlog/requests`）在測試伺服器上不能用**：agent 每次都回 `500:Copyfile fail : Syntax or usage error (&d)`，應該是 Portal 的 Device Log 遠端儲存設定有問題，需要管理者檢查。所以 `fetch_device_log` 預設改用終端機查詢，`source=devlog` 保留為備用（檔案格式尚未驗證）。
- 使用者 session 的執行結果會留在裝置的 Application 事件記錄裡（來源 WSH），本機使用者看得到。

## 程式結構

```
src/deviceon_mcp/
├── server.py           # 入口：建立 FastMCP、依 DEVICEON_TOOLSETS 註冊工具、stdio / HTTP
├── config.py           # 環境變數設定、保護清單
├── client.py           # DeviceOn REST client（Basic / Bearer）
├── senml.py            # 解析 DeviceOn 的 {"bn", "e": [{"n","v"}]} 資料格式
├── analysis.py         # 週期偵測、相關係數（純 Python）
├── confirm_store.py    # 一次性確認 token
├── actions.py          # 共用的兩段式動作：issue_action / confirm_action
├── terminal.py         # DeviceOn 遠端終端機 websocket client
├── remote_exec.py      # 遠端執行（SYSTEM / 使用者 session）、腳本審查
├── deps.py             # 共用依賴（client、terminal、clock、sleep，方便測試注入）
└── tools/
    ├── __init__.py     # TOOLSETS 註冊表（有需要確認的動作時自動加上 confirm_action）
    ├── common/         # list_devices、confirm_action
    ├── diagnose/       # metrics.py、processes.py、windows.py、autostart.py
    ├── control/        # capabilities、power、wake（WOL 代理）、autostart（停用排程／服務）、screenshot、data、kvm、protect
    ├── logs/           # eventlog.py、shutdown.py（關機原因分析）
    └── remote/         # command.py
simulator/
├── windows/            # cpu_hog.exe（C#，build.bat 以內建 .NET Framework 4 編譯）
├── windows-task/       # mem_leak.exe + install.ps1 / uninstall.ps1（工作排程器觸發的記憶體暴增）
├── windows-hang/       # hang_app.exe（WinForms 視窗死結 →「沒有回應」，CPU≈0%、記憶體平穩）
├── windows-shutdown/   # pressure_leak.exe + mem_guard.exe（記憶體壓力累積 → 保護性關機，開機後再犯）
└── stress_sim.py       # Linux 用的 Python 版
scripts/
└── probe_process_fields.py  # 直接看 agent 回報的原始 process 欄位（例如 IsActive）
tests/                  # 包含模擬的 DeviceOn 後端（fake_deviceon.py）
```

**新增領域**（例如 OTA）：建立 `tools/ota/__init__.py` 並提供 `register(mcp, deps)`，加入 `tools/__init__.py` 的 `TOOLSETS`，部署時用 `DEVICEON_TOOLSETS=common,ota` 開啟。

## 安裝（只需做一次）

前置條件：Python 3.10 以上、可連到 DeviceOn Portal、一個 DeviceOn 服務帳號，以及已安裝 `ProcessMonitor` plugin 的目標裝置。

```powershell
cd E:\workspace\DeviceOn\Backend\mcp-server
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"      # Linux/macOS: .venv/bin/pip
.venv\Scripts\python -m pytest             # 預期全部通過，不需要連到 DeviceOn
```

安裝後會產生執行檔 `.venv\Scripts\deviceon-mcp.exe`（Linux/macOS 為 `.venv/bin/deviceon-mcp`）。因為是 editable 安裝，之後修改 `.py` 檔不需要重新安裝（見[修改 MCP Server 的流程](#修改-mcp-server-的流程)）。

**Server 只從環境變數讀取設定，不會讀取 `.env` 檔。** 可用的變數和說明見 [.env.example](.env.example)，它只是一份參考清單。必填的有 `DEVICEON_BASE_URL`（要包含 `/rmm`），以及 `DEVICEON_TOKEN` 或 `DEVICEON_USERNAME` + `DEVICEON_PASSWORD` 其中一組。

> stdio 模式下 stdout 專門用來傳 MCP 協定，所有 log（包括 kill 稽核記錄）都輸出到 stderr。

## 部署到 Claude Code

### 1. 註冊 MCP Server

標準做法：MCP 設定放在 repo 根目錄的 `.mcp.json`（進版控、團隊共用），帳號密碼放在每位成員自己的 Windows 使用者環境變數（不進版控）。

```
Windows 使用者環境變數 ──(Claude Code 啟動時展開 ${VAR})──▶ .mcp.json 的 env ──▶ python -m deviceon_mcp 子程序
```

**步驟 1：設定使用者環境變數（每位成員做一次）**

```powershell
setx DEVICEON_BASE_URL "https://deviceon.wise-paas.com/rmm"
setx DEVICEON_USERNAME "root@advantech.com.tw"
setx DEVICEON_PASSWORD "2022AdvP@ssw0rd"
# 選用：venv 不在預設路徑 E:/workspace/DeviceOn/Backend/mcp-server 時才需要
setx DEVICEON_MCP_PYTHON "E:/workspace/DeviceOn/Backend/mcp-server/.venv/Scripts/python.exe"
```

**步驟 2：完全關閉並重新開啟 VS Code**（或終端機）。`setx` 只對之後新啟動的程式生效，Claude Code 是在啟動時展開 `${VAR}` 的。開一個新的 PowerShell 確認：

```powershell
echo $env:DEVICEON_BASE_URL     # 應顯示剛才設定的網址
```

**步驟 3：`.mcp.json`**（repo 根目錄已附上，內容如下）

```json
{
  "mcpServers": {
    "deviceon": {
      "type": "stdio",
      "command": "${DEVICEON_MCP_PYTHON:-E:/workspace/DeviceOn/Backend/mcp-server/.venv/Scripts/python.exe}",
      "args": ["-m", "deviceon_mcp"],
      "env": {
        "DEVICEON_BASE_URL": "${DEVICEON_BASE_URL}",
        "DEVICEON_USERNAME": "${DEVICEON_USERNAME}",
        "DEVICEON_PASSWORD": "${DEVICEON_PASSWORD}",
        "DEVICEON_TOOLSETS": "common,diagnose,control,logs"
      }
    }
  }
}
```

**步驟 4：在 repo 根目錄啟動 Claude Code**，第一次會跳出視窗詢問是否信任這個專案的 MCP server，選擇同意。

注意事項：
- `.mcp.json` 裡不放任何帳號資訊，可以放心 commit。`DEVICEON_TOOLSETS` 這類非機密的設定直接寫在檔案裡。
- `setx` 會把值以明文存在目前 Windows 使用者的登錄檔（`HKCU\Environment`），同一位使用者執行的程式都讀得到。建議使用權限受限的專用服務帳號。
- DeviceOn 使用自簽憑證時，在 `.mcp.json` 的 `env` 加上 `"DEVICEON_VERIFY_TLS": "false"`。

### 2. 設定工具權限與 timeout（安全關鍵，不要省略）

合併到 repo 根目錄的 `.claude/settings.json`：

```json
{
  "permissions": {
    "allow": [
      "mcp__deviceon__list_devices",
      "mcp__deviceon__analyze_metric_periodicity",
      "mcp__deviceon__get_current_metrics",
      "mcp__deviceon__capture_top_processes",
      "mcp__deviceon__find_unresponsive_windows",
      "mcp__deviceon__get_device_capabilities",
      "mcp__deviceon__request_kill_process",
      "mcp__deviceon__take_screenshot",
      "mcp__deviceon__fetch_device_log",
      "mcp__deviceon__request_power_action",
      "mcp__deviceon__request_set_data",
      "mcp__deviceon__request_kvm_session",
      "mcp__deviceon__request_protection_action",
      "mcp__deviceon__request_recovery_action",
      "mcp__deviceon__request_run_command",
      "mcp__deviceon__find_process_autostart",
      "mcp__deviceon__find_wol_relay_candidates",
      "mcp__deviceon__wait_for_device_online",
      "mcp__deviceon__analyze_last_shutdown",
      "mcp__deviceon__request_configure_wol",
      "mcp__deviceon__request_disable_autostart"
    ],
    "ask": [
      "mcp__deviceon__confirm_action"
    ]
  },
  "env": {
    "MCP_TOOL_TIMEOUT": "660000"
  }
}
```

- 讀取類工具自動放行，Demo 時不會一直跳出確認視窗。
- `confirm_action` 一律詢問：就算 Agent 誤以為使用者已經同意，Claude Code 也會再跳出確認視窗。加上 server 端的 token 機制，總共有兩道關卡。
- `request_*` 可以放行，因為它們只回傳摘要和 token，不會改變裝置。
- 要開啟 control／logs／remote，在 `.mcp.json` 的 env 設 `"DEVICEON_TOOLSETS": "common,diagnose,control,logs"`；`remote` 另外要加 `"DEVICEON_ALLOW_REMOTE_COMMAND": "true"`。
- `MCP_TOOL_TIMEOUT`（毫秒）：`capture_top_processes` 最長會執行 600 秒，設為 11 分鐘可以避免工具執行到一半被中斷。

### （選用）YOLO 模式：跳過確認

讓 LLM 反覆調整、試跑指令時，不用每次都經過「`request_*` → 詢問使用者 → `confirm_action`」。設計與限制見[安全設計](#安全設計)的 YOLO 模式說明。

**開啟後的差別**

| | 一般模式 | YOLO 模式（列在 `DEVICEON_AUTO_CONFIRM` 的動作） |
|---|---|---|
| `request_*` | 只檢查，回傳摘要和 `confirm_token` | 檢查後**直接執行**，回傳結果與 `auto_confirmed: true` |
| Agent 是否先問使用者 | 要 | 不用，但執行後要說明做了什麼 |
| `confirm_action` | 每次都要 | 不需要；只有被判定為風險的請求（回傳 `auto_confirm_skipped`）才會用到 |
| Claude Code 確認視窗 | `confirm_action` 每次跳出 | 不跳出（`request_*` 在 `allow`）；風險請求仍會跳出 |

**步驟 1：在共用的 `.mcp.json` 的 `env` 加一行**（預設空值等於關閉，可以放心 commit）

```json
"DEVICEON_AUTO_CONFIRM": "${DEVICEON_AUTO_CONFIRM:-}"
```

**步驟 2：要用的人在自己的電腦上設定**

```powershell
setx DEVICEON_AUTO_CONFIRM "run_command"      # 只讓遠端指令免確認（建議）
# setx DEVICEON_AUTO_CONFIRM "run_command,kill_process"
# setx DEVICEON_AUTO_CONFIRM "all"            # 全部免確認，包括關機、還原，不建議
```

可用的名稱：`run_command`、`kill_process`、`power`、`set_data`、`kvm`、`protection`、`recovery`、`wol_config`、`disable_autostart`，或 `all`。

**步驟 3：確認列出的動作所屬的 toolset 有開**。例如 `run_command` 需要 `DEVICEON_TOOLSETS` 包含 `remote`，並設定 `DEVICEON_ALLOW_REMOTE_COMMAND=true`；`kill_process`、`power` 等需要 `control`。沒開的話 server 會拒絕啟動。

**步驟 4：完全關閉 VS Code 再重新開啟**（`${VAR}` 是 Claude Code 啟動時展開的，只在 `/mcp` 重新連線不夠）。

**確認是否生效**：用 `claude --debug` 啟動，stderr 會出現：

```
WARNING deviceon_mcp.audit: YOLO mode: these actions run WITHOUT confirmation: run_command
```

**關閉**：`setx DEVICEON_AUTO_CONFIRM ""`，再重新啟動 VS Code。

注意事項：
- `run_command` 在 YOLO 下只自動執行**沒有風險警示**的腳本。腳本裡有刪除、格式化、關機、停服務、kill、改登錄檔、下載、動態執行等寫法時，仍會回傳 token 並跳出確認視窗。
- 保護清單、PID 重用、拒絕 `-EncodedCommand`、腳本長度、裝置在線等檢查都照做，不會因為 YOLO 而跳過。
- 每次自動執行都會在稽核記錄留下 `action auto-confirmed (YOLO)`。
- **不要和 HTTP 模式一起用**：HTTP 端點沒有認證，能連到 port 的人就能直接執行動作。
- 只在個人的開發／測試環境使用，不要把實際的值寫死在共用的 `.mcp.json`；OpenClaw 正式工單也不要開。

### 3. 確認連線

```powershell
claude mcp list          # 預期：deviceon: ... - ✓ Connected
```

進入 Claude Code 後輸入 `/mcp`，確認 `deviceon` 顯示 connected，並列出 6 個工具。

### 停用或移除

- 個人暫時停用：在 Claude Code 中輸入 `/mcp`，選擇 `deviceon` 後停用。
- 團隊移除：刪除 `.mcp.json` 中的 `deviceon` 項目並 commit。
- 清除個人的帳號資訊：`setx DEVICEON_PASSWORD ""`，或到「系統內容 → 環境變數」中刪除。

## 部署到 OpenClaw

OpenClaw 用標準 MCP client 連線即可，不需要修改這個 server。實際的設定檔位置和欄位名稱依 OpenClaw 版本而定，以下是需要提供給它的資訊。

**stdio（OpenClaw 和 MCP Server 在同一台機器）**

| 欄位 | 值 |
|---|---|
| command | `E:/workspace/DeviceOn/Backend/mcp-server/.venv/Scripts/python.exe` |
| args | `-m deviceon_mcp` |
| env | `DEVICEON_BASE_URL`、`DEVICEON_USERNAME` / `DEVICEON_PASSWORD`（或 `DEVICEON_TOKEN`）、`DEVICEON_TOOLSETS` |

帳號資訊沿用 Claude Code 那一節設定的 Windows 使用者環境變數：如果 OpenClaw 的設定支援 `${VAR}` 展開，或啟動子程序時會繼承環境變數，設定檔裡就不需要寫密碼。如果都不支援，才把值直接寫進 OpenClaw 的設定，並確保那個檔案不會進版控。

如果 OpenClaw 接受常見的 `mcpServers` JSON 格式（以直接寫值為例）：

```json
{
  "mcpServers": {
    "deviceon": {
      "command": "E:/workspace/DeviceOn/Backend/mcp-server/.venv/Scripts/python.exe",
      "args": ["-m", "deviceon_mcp"],
      "env": {
        "DEVICEON_BASE_URL": "https://<DeviceOn主機>/rmm",
        "DEVICEON_USERNAME": "mcp-agent@example.com",
        "DEVICEON_PASSWORD": "<密碼>",
        "DEVICEON_TOOLSETS": "common,diagnose,control,logs"
      }
    }
  }
}
```

**Streamable HTTP（OpenClaw 在另一台機器）**：見下方 [HTTP 模式](#選用http-模式)，連線網址為 `http://<主機>:8765/mcp`。

**在 OpenClaw 端務必確認：**

1. **工具呼叫的 timeout 至少 11 分鐘**，否則 `capture_top_processes` 會被中斷。
2. **`confirm_action` 需要人工核准。** 如果 OpenClaw 支援依工具設定核准規則，請對這個工具開啟。如果不支援，就只剩 server 端的兩段式 token 這一道關卡；server 的 `instructions` 和工具描述都有要求 Agent 先詢問使用者，但這只靠模型自律。
3. **依 ServerClaw 的工單類型選擇 toolset**：每種工單用不同的 `DEVICEON_TOOLSETS` 設定啟動（例如只看不動的巡檢工單用 `common,diagnose,logs`；需要排除問題、可能要 kill 或重開機的工單再加上 `control`）。

## （選用）HTTP 模式

MCP Server 和 Agent 不在同一台機器時使用：

```powershell
# 伺服器端
.venv\Scripts\deviceon-mcp.exe --transport streamable-http --host 127.0.0.1 --port 8765

# Claude Code 端
claude mcp add --transport http deviceon http://<主機>:8765/mcp
```

> ⚠️ **目前的 HTTP 端點沒有任何認證**，能連到這個 port 的人都能呼叫 kill。只能綁定 `127.0.0.1` 並透過 SSH tunnel 使用，或是放在有認證的反向代理後面。PoC 階段建議只用 stdio。

## 修改 MCP Server 的流程

Agent（Claude Code 或 OpenClaw）只在啟動或重新連線時載入 MCP Server。**每次修改後都必須重新連線**，新的程式碼和工具清單才會生效。

```
修改程式 → 補測試 → pytest → （選做）Inspector 驗證 → 重新連線 → 對話實測 → commit
```

**1. 修改程式並補測試**
- 只改邏輯：在 `tests/test_tools.py` 或 `tests/test_analysis.py` 補上或調整測試案例。
- 呼叫新的 DeviceOn API：先在 `tests/fake_deviceon.py` 加入模擬回應，格式照 WebApp 的 apidoc（例如 `WebApp/src/main/java/com/rest/**/*APIDoc.java`）。

**2. 跑測試**

```powershell
cd E:\workspace\DeviceOn\Backend\mcp-server
.venv\Scripts\python -m pytest
```

改到「什麼時候可以 kill」相關的邏輯時（保護清單、PID 重用檢查、token 機制），一定要確認以下測試仍然通過：`test_protected_process_is_refused`、`test_request_does_not_kill`、`test_confirm_aborts_when_pid_reused`、`test_full_kill_flow_and_token_is_single_use`。

**3.（選做）用 MCP Inspector 從協定層檢查**

改了工具名稱、參數或描述時，可以用它看 LLM 實際拿到的 schema，也能手動呼叫工具：

```powershell
$env:DEVICEON_BASE_URL="https://<主機>/rmm"; $env:DEVICEON_USERNAME="..."; $env:DEVICEON_PASSWORD="..."
npx @modelcontextprotocol/inspector .venv\Scripts\deviceon-mcp.exe
```

**4. 重新連線**
- Claude Code：輸入 `/mcp`，選擇 `deviceon`，再選 **Reconnect**；或重新啟動 Claude Code。
- OpenClaw：依它的方式重新載入 MCP Server，或重新啟動 OpenClaw。

**5. 實測**：確認工具清單已經是新的，再用對話跑一次相關流程。

**6. Commit**

### 不同的修改，要多做什麼

| 改了什麼 | 除了重新連線，還要做什麼 |
|---|---|
| 只改工具內部邏輯 | 不需要 |
| 工具的描述或參數 | 用 Inspector 看一次 schema。Agent 只在連線時抓工具清單，不重新連線會一直用舊的描述 |
| **工具改名，或新增工具** | 更新 `.claude/settings.json` 的 `allow` / `ask`（權限是依工具全名 `mcp__deviceon__<工具名>` 比對的）。**新增的寫入類工具一定要放進 `ask`**，在 OpenClaw 也要設定核准 |
| 刪除工具 | 從 `.claude/settings.json` 移除對應規則 |
| 新增 toolset（例如 `tools/ota/`） | 在 `tools/__init__.py` 的 `TOOLSETS` 註冊；在 MCP 設定的 `DEVICEON_TOOLSETS` 加上新名稱；更新權限 |
| `pyproject.toml`（相依套件、entry point） | 重新執行 `.venv\Scripts\pip install -e ".[dev]"` |
| 帳號、密碼、URL | 用 `setx` 更新後，**完全重新啟動 VS Code**（只在 `/mcp` 重新連線不夠，因為 `${VAR}` 是 Claude Code 啟動時展開的）。OpenClaw 則重新啟動 OpenClaw |
| `.mcp.json` 內容（toolset、TLS 等） | 在 `/mcp` 重新連線；若沒生效，重新啟動 Claude Code |

### Windows 上要注意的事

- **用 `python.exe -m deviceon_mcp` 啟動，不要用 `deviceon-mcp.exe`。** server 執行中時 exe 會被鎖住，這時 `pip install -e .` 會在覆寫 exe 時失敗，而且失敗前已經移除了舊的安裝資訊（`site-packages` 裡只剩 `~eviceon_mcp-0.1.0.dist-info`、`__editable__…pth` 不見），下次啟動就會 `ModuleNotFoundError: No module named 'deviceon_mcp'`，Claude Code 顯示 `CONNECTION_CLOSED`。用 python.exe 啟動就不會鎖住 exe。已經壞掉時：關掉所有使用 deviceon 的 Claude Code session，再執行一次 `pip install -e .`。
- **查看 server 的 log**：用 `claude --debug` 啟動 Claude Code，MCP Server 的 stderr 會一起顯示。也可以在終端機直接執行 `deviceon-mcp.exe`，看啟動時的錯誤訊息。
- **確認 token 存在記憶體中**，重新連線後會全部失效。如果在 `request_kill_process` 之後才重新連線，要重新申請 token。

## 疑難排解

| 現象 | 可能原因 | 處理方式 |
|---|---|---|
| `/mcp` 顯示 `CONNECTION_CLOSED`，直接啟動時出現 `No module named 'deviceon_mcp'` | `pip install -e .` 在 exe 被鎖住時失敗，安裝只剩一半 | 見[Windows 上要注意的事](#windows-上要注意的事) |
| `claude mcp list` 顯示 Failed | exe 路徑錯誤，或缺少必填的環境變數 | 直接執行 `deviceon-mcp.exe`，看 stderr 的錯誤訊息（例如 `DEVICEON_BASE_URL is required`） |
| 錯誤訊息提到變數未設定，但明明已經 `setx` 過 | VS Code 是在 `setx` 之前開啟的，讀不到新的值 | 完全關閉 VS Code（包括所有視窗）再重新開啟；用新的 PowerShell 執行 `echo $env:DEVICEON_BASE_URL` 確認 |
| 放了 `mcp-server/.env` 但沒有作用 | Server 不讀 `.env` 檔 | 改用 `setx` 設定環境變數 |
| 工具回傳 `DeviceOn API error 0` | 連不到 DeviceOn | 確認 URL 有加上 `/rmm`，以及網路或代理設定 |
| 工具回傳 `error 403` | 帳號密碼錯誤、帳號被鎖，或權限不足 | 用同一組帳號登入 Portal 測試；確認帳號對該裝置群組有權限 |
| SSL 相關錯誤 | DeviceOn 使用自簽憑證 | 設定 `DEVICEON_VERIFY_TLS=false` |
| `list_devices` 回傳 0 台 | 服務帳號沒有被指派裝置 | 在 DeviceOn 中把裝置群組授權給該帳號 |
| 分析結果顯示 `only N samples` | 歷史資料不足 | 等更久，或確認 CPU Usage 有開啟歷史資料儲存 |
| 分析結果出現 `too coarse` | 回報 interval 太長 | 把裝置的回報 interval 調到 10 秒以下 |
| `unique_snapshots` 太少 | Portal 端快取了 process 清單 | 加長 `duration_sec` |
| `capture_top_processes` 中途逾時 | Agent 端的工具 timeout 太短 | Claude Code 檢查 `MCP_TOOL_TIMEOUT` 後重新啟動；OpenClaw 調整它的工具 timeout |
| 啟動失敗，訊息是 `DEVICEON_AUTO_CONFIRM has unknown or not-enabled action(s)` | YOLO 的動作名稱拼錯，或所屬的 toolset 沒開 | 對照訊息列出的 enabled actions 修正；例如 `run_command` 要開 `remote` 並設 `DEVICEON_ALLOW_REMOTE_COMMAND=true` |
| 開了 YOLO 還是要確認 | 腳本命中風險樣式（回傳裡有 `auto_confirm_skipped`），或該動作沒列在 `DEVICEON_AUTO_CONFIRM` | 風險腳本本來就要確認；其他情況檢查變數值，並完全重新啟動 VS Code |
| 修改程式後沒有生效 | 沒有重新連線 | 見[修改 MCP Server 的流程](#修改-mcp-server-的流程)第 4 步 |

## PoC Demo 步驟

1. **裝置端**：確認 agent 已安裝 `ProcessMonitor` plugin；在 DeviceOn 把該裝置的回報 interval 調到 5–10 秒，並讓 `System Monitor Info / CPU Usage` 存入歷史資料。
2. **啟動模擬程式**：
   - **Windows**：在任一台 Windows 執行 `simulator\windows\build.bat`，產生 `cpu_hog.exe`（使用內建的 .NET Framework 4 編譯，不需要安裝 Python），複製到裝置上執行：
     ```bat
     cpu_hog.exe                          :: 預設：高負載 60 秒 / 閒置 120 秒，所有核心，無限循環
     cpu_hog.exe --high 60 --low 120 --threads 4 --cycles 10
     taskkill /im cpu_hog.exe /f          :: 手動停止（或在視窗按 Ctrl+C）
     ```
   - **Linux**：
     ```bash
     cp "$(command -v python3)" /tmp/cpu_hog      # 讓 process 名稱好認，否則會顯示成 python3
     /tmp/cpu_hog stress_sim.py --high 60 --low 120
     ```
3. **等 15–20 分鐘**，累積至少 4 個週期的歷史資料。
4. **對 Agent 說**：「幫我看一下 <裝置名稱> 最近是不是怪怪的」。預期的流程：
   `list_devices` → `analyze_metric_periodicity`（periodic=true, period≈180s）→ `capture_top_processes`（duration ≥ 180s，suspect=cpu_hog）→ `request_kill_process` → **Agent 詢問使用者** → `confirm_action` → 等一個週期後再跑 `analyze_metric_periodicity` 確認尖峰已消失。

### 情境二：工作排程器觸發的記憶體暴增（Windows）

模擬「某個排程工作每次執行都吃掉大量記憶體」。`mem_leak.exe` 每次執行都會在 `GrowSeconds` 內逐步配置記憶體（每個 page 都寫入，確保真的進入 working set），維持 `HoldSeconds` 後結束並釋放記憶體。工作排程器每 `IntervalMinutes` 啟動一次，所以：

- 系統記憶體使用率（`/System Monitor Info/usagePhysMem`）會呈現鋸齒狀的週期變化。
- **每一輪都是新的 PID**，而且 process 在兩輪之間不存在。kill 只能結束這一輪，真正的解法是停用排程。這可以測試 Agent 會不會看出這一點。

```powershell
cd simulator\windows-task
.\build.bat                                   # 產生 mem_leak.exe（沒有視窗，進度寫到 log）
# 複製 mem_leak.exe、install.ps1、uninstall.ps1 到裝置上，在裝置上執行：
.\install.ps1                                 # 預設：每 5 分鐘，成長 120 秒、維持 30 秒，上限 2048 MB
.\install.ps1 -IntervalMinutes 3 -GrowSeconds 60 -HoldSeconds 30 -MaxMB 1024 -RunNow
Get-Content $env:LOCALAPPDATA\DeviceOnSim\mem_leak.log -Wait   # 看每一輪的 PID 與配置量
.\uninstall.ps1                               # 移除排程、結束 process、刪除安裝目錄
```

| 參數 | 預設 | 說明 |
|---|---|---|
| `-IntervalMinutes` | 5 | 觸發間隔；`GrowSeconds + HoldSeconds` 必須比它短至少 30 秒，否則會拒絕安裝 |
| `-GrowSeconds` / `-HoldSeconds` | 120 / 30 | 成長時間 / 維持時間 |
| `-MaxMB` / `-MaxPercent` | 2048 / 40 | 配置上限，取兩者中較小者（`MaxPercent` 是佔實體記憶體的比例，最高 80） |
| `-FloorPercent` | 15 | 可用記憶體低於實體記憶體的這個比例時就停止成長（保護裝置） |
| `-RunNow` | 關閉 | 安裝後立刻跑一輪；否則 1 分鐘後才開始 |

- 排程建立在 `\DeviceOnSim\MemLeak`，以目前使用者身分、只在登入時執行（不儲存密碼）。執行時間超過 `GrowSeconds + HoldSeconds + 120` 秒會被排程器強制結束；同一時間只會有一個 instance。
- 如果裝置本身的記憶體已經很滿，`FloorPercent` 會讓它幾乎配置不了任何記憶體（log 會寫 `below floor`），這時候就看不到效果。可以先調低 `-FloorPercent`，或關掉其他程式。
**建議參數要依裝置的記憶體大小調整**：配置量至少要達到總記憶體的 20% 以上，才能明顯超過背景雜訊。實測 DESKTOP-MT3CC6E（30 GB）閒置時，`usagePhysMem` 在 1 小時內自然擺動約 7 個百分點；預設的 2048 MB 只佔 6.5 個百分點，會被雜訊淹沒。這台建議使用：

```powershell
.\install.ps1 -IntervalMinutes 6 -GrowSeconds 120 -HoldSeconds 150 -MaxMB 8192
```

約 26 個百分點；高點持續約 3–4 個樣本（裝置每 60 秒回報一次）；30 分鐘的視窗可以看到 5 輪。

**預期的 Agent 流程**：
`analyze_metric_periodicity(sensor="memory")`（periodic=true，`next_step_hint` 會提示改用 `metric='memory'`）→ `capture_top_processes(metric="memory", duration_sec ≥ period_sec)` → suspect 是 `mem_leak.exe`，附有 `pids_seen` 和 `recurrence_hint` → Agent 應該告訴使用者「kill 只能結束這一輪，要去停用排程」。

**`metric="memory"` 如何判斷**：
- 系統序列使用同一份快照中的 `totalPhysMemKB - availPhysMemKB`；各 process 使用 `Mem Usage`（單位是 KB，已在實機確認）。
- 系統已使用量至少要變動 `max(500 MB, 總記憶體的 5%)`，才算抓到尖峰。
- 判斷依據是**增加量**（`spike_delta_mb`＝高點時的平均減掉平時的平均），不是絕對用量。平常就佔 250 MB 的 explorer.exe 不會被誤判。
- 同一個名稱的 PID 換了、但從來沒有同時存在，就合併成一筆（`pids_seen`），並在 suspect 附上 `lifecycle` 與 `recurrence_hint`。CPU 模式也適用這個規則。
- `system_memory.explained_by_listed_processes`：清單中 process 的增加量能解釋系統增加量的比例。低於 0.5 時會提醒「元兇可能是 agent 沒有回報的 process」。實測這台 agent 的清單只涵蓋約 56% 的已使用記憶體，系統服務可能不在清單裡。
- 用 CPU 模式抓 process 時，如果 CPU 沒有尖峰、但記憶體有明顯變化，notes 會提示改用 `metric='memory'`。

### 情境三：視窗程式死結，顯示「沒有回應」（Windows）

模擬「程式沒有吃 CPU 也沒有吃記憶體，但畫面卡死」。`hang_app.exe` 是一個 WinForms 視窗，上面有每秒加 1 的計數器。`--after` 秒後，UI thread 和一個 worker thread 會互相等待：worker 先拿到鎖，再用 `Control.Invoke` 等 UI thread 執行；UI thread 則在等那把鎖。結果：

- 計數器停住，約 5 秒後 Windows 把視窗標成「沒有回應」（`Process.Responding == false`）。
- CPU 約 0%、記憶體不變，所以 `analyze_metric_periodicity` 和 `capture_top_processes` **都看不出異常**，要靠 `find_unresponsive_windows` 才找得到。
- 兩個 thread 都卡在一般的 user-mode wait，`taskkill /f` 或 `request_kill_process` + `confirm_action` 可以正常結束它（已在本機驗證）。

```powershell
cd simulator\windows-hang
.\build.bat                         # 產生 hang_app.exe
# 複製到裝置上，在「已登入使用者的桌面」執行（不能用 SYSTEM 或服務身分，否則看不到視窗）：
.\hang_app.exe                      # 30 秒後死結
.\hang_app.exe --after 60           # 60 秒後死結
.\hang_app.exe --after 0            # 只在按下按鈕時死結
taskkill /im hang_app.exe /f        # 結束
Get-Content $env:TEMP\deviceon-sim\hang_app.log   # PID、啟動時間、死結時間
```

**預期的 Agent 流程**：使用者說「某台機器上的程式卡住了」→ `analyze_metric_periodicity`／`get_current_metrics` 看起來正常 → `find_unresponsive_windows` → `not_responding` 裡有 `hang_app.exe`（pid、視窗標題）→ （選用）`take_screenshot` 看畫面 → `request_kill_process` → 詢問使用者 → `confirm_action`。

實測（2026-11-18，DESKTOP-MT3CC6E）：`find_unresponsive_windows` 約 3 秒完成，正確找出 `hang_app.exe`。背景被 Windows 暫停的 UWP 程式（例如 `SystemSettings.exe`）也會回報 `Responding=False`，所以另外列在 `suspended_by_windows`，不算卡死。

**為什麼不從 agent 的 process 清單判斷**：API 文件裡每個 process 有 `IsActive` 欄位，但用 `scripts/probe_process_fields.py` 實測，這台 agent **完全沒有回報這個欄位**，只有 `Name`、`PID`、`Owner`、`CPU Usage`、`Mem Usage`。所以改用遠端執行，在使用者 session 裡檢查 `Process.Responding`（見[遠端執行是怎麼做的](#遠端執行是怎麼做的)）。probe 腳本仍保留，可以用來檢查其他 agent 版本有沒有回報新欄位：

```powershell
python scripts\probe_process_fields.py --device <裝置名稱> --name hang_app --duration 180
```

### 情境四：記憶體壓力累積 → 保護性關機 → 透過鄰近裝置喚醒 → 分析原因並修正（Windows）

模擬「某個程式的記憶體只增不減，最後監控程式為了保護機台把它關機，而且每次開機都會再犯」。有兩個程式，分別扮演**元兇**和**按下關機的人**：

| 程式 | 角色 | 行為 |
|---|---|---|
| `pressure_leak.exe` | 元兇 | 開機後延遲 `-LeakStartDelaySec` 秒，每分鐘多配置 `-LeakMBPerMin` MB 且永不釋放，並輪流重寫已持有的記憶體（約每 20 秒一輪）讓它留在 RAM；實體負載到 `-LeakMaxLoadPercent` 或 commit 到 `-LeakMaxCommitPercent` 時停止成長、繼續持有；發生 OOM 後暫停 60 秒 |
| `mem_guard.exe` | 保護性監控（模擬工業機台常見的 watchdog） | **實體負載 ≥ `-ThresholdPercent` 或 commit ≥ `-CommitThresholdPercent`** 持續 `-SustainSeconds` 秒 → 在 Application 記錄寫入警告（來源 `DeviceOnSim`、事件 3001，列出前 5 名記憶體使用者）→ 有 `-Arm` 才真的呼叫 `InitiateSystemShutdownEx` 關機（S5，WOL 叫得醒）。每 5 分鐘記一行 heartbeat |

> **第一次實機測試（2026-11-19，DS054，16 GB，`-LeakMBPerMin 2048`）沒有關機，原因**：舊版 leak 每個 page 只寫一次，Windows 把它們換頁到 page file，實體負載一直在 30–77% 擺動；leak 持有到 40 GB、commit 用完（`OutOfMemoryException`），機器因大量換頁而卡死，但只看實體負載的 mem_guard 從未觸發。現在 guard 也看 commit（Windows 上的「記憶體用完」指的是 commit），leak 會保持記憶體常駐並在 commit 95% 停下。速率建議不要超過 512 MB/min（腳本上限 1024）。

兩個都是以 SYSTEM 身分、**開機時**啟動的排程工作（`\DeviceOnSim\PressureLeak`、`\DeviceOnSim\MemGuard`），所以被 WOL 喚醒後，即使沒人登入，記憶體又會開始累積。真正的修正是停用 `PressureLeak` 排程，kill 只能撐到下次開機。

```powershell
cd simulator\windows-shutdown
.\build.bat                                   # 產生 pressure_leak.exe、mem_guard.exe（x64）
# 複製 *.exe、install.ps1、uninstall.ps1 到裝置上，以系統管理員執行：
.\install.ps1 -RunNow                         # 演練：全部照做，但只記錄 DRY RUN，不關機
.\install.ps1 -Arm -RunNow                    # 實際：腳本會依目前的實體負載與 commit 印出預估觸發時間
.\install.ps1 -Arm -RunNow -LeakMBPerMin 512  # 加快（建議上限）
Get-Content C:\ProgramData\DeviceOnSim\Shutdown\mem_guard.log -Wait
.\uninstall.ps1                               # 移除排程、結束 process、取消已排定的關機（shutdown /a）
```

**WOL 前置條件**（這個情境的前提，DeviceOn 無法替你檢查）：裝置 BIOS 開啟 Wake on LAN／PME、關閉 ErP／Deep Sx；網卡允許 Magic Packet 喚醒；有線網路；在 Portal 把 WOL 設成「代理模式」，代理裝置要和它在**同一個廣播網域**且在線。

**預期的 Agent 流程**：

1. `list_devices(offline_only=true)` → 發現 DS054-H5T3KU4 離線，`wakeOnLan.mode = agent`
2. `find_wol_relay_candidates(did)` → 列出在線且同子網路的裝置（用候選裝置自己的 `Get-NetIPAddress` 判斷，不是猜 /24）。目前的代理裝置已經合適就回報「不需更改」；否則**詢問使用者**後 `request_configure_wol(mode='agent', relay_did=…)` → `confirm_action`
3. `request_power_action(action='start')` → 詢問使用者 → `confirm_action` → `wait_for_device_online`（Portal 每 10 秒重送一次，最多 10 分鐘）
4. `analyze_last_shutdown(did)` → `kind=initiated`、`initiated_by=mem_guard.exe`；`suspects[0]=pressure_leak.exe`（證據：關機註解、事件 2004、離線前 DeviceOn 的記憶體曲線持續上升）；`findings` 指出 mem_guard 只是按下按鈕，而且 pressure_leak.exe **開機後又在跑了**
5. 向使用者說明原因與解方 → 詢問 → `request_kill_process` + `find_process_autostart(['pressure_leak.exe'])` → `request_disable_autostart(kind='scheduled_task', name='\DeviceOnSim\PressureLeak')` → `confirm_action`

**DeviceOn 的 WOL 是怎麼運作的**（已讀過後端原始碼）：`PUT /power/device action=start` 變成 `commCmd 999`，Worker 攔下來不轉給 agent，每 10 秒依 `wolmode` 送一次 magic packet，直到裝置上線或 10 分鐘逾時：1＝伺服器自己廣播、2＝要求 `wolrepeater` 指定的在線 agent 在它的 LAN 廣播（`commCmd 85` + 目標 MAC）、3＝送到 `wolrepeater` 的 IP。`wolmode=0` 或代理裝置離線時 **Worker 什麼都不做，10 分鐘後才回報失敗**，所以 `request_power_action(start)` 會先擋下來。

**已在實機驗證（2026-11-20）**：
- `find_wol_relay_candidates(DS054)`：DESKTOP-MT3CC6E（172.22.12.255）和 wunhuei-desttop 都回報 `172.22.12.0/22`，包含 DS054 的 172.22.13.77。這兩個 IP 用 /24 判斷會被誤判成不同網段；Ubuntu 裝置標示為未驗證。
- `analyze_last_shutdown(DS054)`：正確判斷上一次是使用者從開始功能表關機（`StartMenuExperienceHost.exe`、`interactive=true`），沒有誤指嫌疑程式。順便發現 DS054 在關機前後 CAgent.exe（EmbDDC.dll，0xc0000005）和 DeviceOn Agent 的 WindowsFeature.exe 多次 crash。
- `find_process_autostart`、`request_disable_autostart` 的狀態讀取：正確找到 Edge 的排程與服務；agent 服務 `DeviceOnAgent` 會被拒絕。
- 尚未實機跑過：模擬器實際關機、`PATCH /devices/wol`、透過 MCP 送出 `start`、停用排程的執行階段（都是寫入動作，需要你在場時跑）。

**判斷邏輯的設計**：
- 事件欄位一律從 XML 依名稱讀取（1074 的 `param1..7`、41 的 `BugcheckCode`／`PowerButtonTimestamp`、1000 的 `AppName`），不解析訊息文字，所以中文 Windows 也適用。
- `kind`：`bugcheck`（藍屏）、`forced_power_button`（長按電源）、`unexpected`（斷電、當機、過熱）、`initiated`（有人或程式要求關機）、`clean_unknown`、`unknown`。
- 只有在**有資源壓力的證據**時（事件 2004、離線前記憶體上升、或程式名稱出現在關機註解）才會說「X 只是按下按鈕，元兇是 Y」。Application Error、.NET Runtime、RestartManager、WMI 這類每次關機都會出現的事件只列為 crash 清單，不算嫌疑。

## 第一次接實機時要確認的事

已在實機驗證（2026-11，Windows 10 agent）：透過 intermittent report 可以取得完整 process 清單，每個 process 都有 `Name`、`PID`、`Owner`、`CPU Usage`；`/histdata` 和週期分析可正常運作。

以下項目還沒在實機上驗證過：

| 項目 | 若不符合 |
|---|---|
| Linux agent 是否同樣支援 ProcessMonitor 的 intermittent report | `capture_top_processes` 會回報 `process_list_available: false` |
| Linux agent 的 process `CPU Usage` 是「佔整機 %」還是「佔單核 %」 | 相關係數不受影響；`suspect` 判斷中「≥ 30% 系統 CPU」的門檻可能需要調整 |
| `/histdata` 的時間戳 `ts` 是 epoch 毫秒 | 修改 `metrics.analyze_metric_periodicity` 的解析 |
| `/v1/devicegroups/devices` 的 `no` 是否從 1 開始 | 修改 `client.list_devices` 的 `page_no` |
| 服務帳號是否需要 `onlyMine=false` 才看得到所有裝置 | 在 `client.list_devices` 加上這個參數 |
| 溫度 plugin 的名稱和 sensor 路徑 | 設定 `DEVICEON_TEMP_PLUGIN` / `DEVICEON_TEMP_SENSOR` |

## 已知限制

- 取樣間隔不會短於 intermittent report 的上傳間隔（2–10 秒，依 `duration_sec / samples` 決定），重複的快照會自動去重，並回報 `unique_snapshots`。
- 每次抓 process 都會觸發 intermittent report，在取樣期間增加 agent 上傳量和 Portal 的寫入量（每 2–10 秒一份完整 process 清單）。只在診斷時短暫使用，不適合常態輪詢。
- 裝置離線時無法觸發 intermittent report，抓 process 的工具會直接回報錯誤。
- 使用 Basic 認證時，每個請求都會觸發一次登入（bcrypt 驗證和稽核）。正式環境建議改用 `DEVICEON_TOKEN`。
- 確認 token 存在記憶體中，server 重啟後就會失效（這是刻意的設計）。多實例部署時需要改用共享儲存。
- 無法取得 CPU 頻率（DeviceOn 沒有回報這個欄位）；溫度需要研華硬體加上 SUSI。
- 週期分析以 p95 作為「高點」，等於假設尖峰至少佔 5% 的樣本：
  - **剛開始的異常**：已經處理。整個視窗判定不顯著時，會依序改用最近 1/2、1/4、1/8 的視窗重算，判斷標準不變，片段最短 10 分鐘、10 個樣本。成功時會回傳 `analyzed_window_min` 和 `pattern_started_at`（從最新的尖峰往回推，直到週期中斷為止）。這不需要多抓資料。實機驗證：DESKTOP-MT3CC6E 在 180 分鐘視窗中原本判定不顯著，改用最近 90 分鐘後抓到週期 360.8 秒，起始時間 13:49，與排程安裝的時間吻合。
  - **尖峰佔的時間太短**：還沒處理。例如每 20 分鐘只尖峰 30 秒（佔 2.5%），不管視窗多長都抓不到。
  - **已經停止的異常**：例如只出現在視窗前段，後來 process 被 kill 了。這種情況不會特別去找，因為設計上關注的是「現在是否還在發生」。
