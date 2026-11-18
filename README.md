# DeviceOn MCP Server（PoC）

讓 AI Agent 透過 MCP 呼叫 DeviceOn Portal REST API：偵測裝置的週期性 CPU 異常、找出造成異常的 process，並在使用者同意後結束它。

```
AI Agent (OpenClaw)  ──MCP──▶  DeviceOn MCP Server  ──REST /rmm/v1──▶  DeviceOn Portal  ──MQ──▶  Edge Agent
```

不需要修改 DeviceOn 後端，只使用既有的 API。

## 工具

| Toolset | 工具 | 類型 | 呼叫的 DeviceOn API |
|---|---|---|---|
| common | `list_devices` | 讀 | `GET /v1/devicegroups/devices` |
| diagnose | `analyze_metric_periodicity` | 讀 | `GET /v1/devices/{did}`、`GET /v1/data/devices/{did}/histdata` |
| diagnose | `get_current_metrics` | 讀 | `GET /v1/data/devices/{did}/latestdata?source=autoreport` |
| diagnose | `capture_top_processes` | 讀 | `PUT /v1/devicectrl/intermittent_report` + `GET /v1/data/devices/{did}/latestdata`（取樣多次） |
| diagnose | `request_kill_process` | 讀（只發 token） | 同上（取一份最新的 process 清單） |
| diagnose | `confirm_kill_process` | **寫（破壞性）** | 同上 + `PUT /v1/processes`（`action: kill`） |

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

- **兩段式 kill**：`confirm_kill_process` 只接受 `request_kill_process` 發出的 token，不接受 pid。Agent 無法跳過「詢問使用者」這一步。token 只能用一次，預設 5 分鐘後失效，只存在記憶體中。
- **PID 重用保護**：確認 kill 前會重新讀取 process 清單；如果 pid 已經屬於其他程式名稱，就中止並回報 `aborted_pid_reused`。
- **保護清單**：系統關鍵 process 和 DeviceOn agent 本身（`cagent`、`systemd`、`lsass.exe` 等，見 [config.py](src/deviceon_mcp/config.py)）一律拒絕。可以用 `DEVICEON_PROTECTED_PROCESSES` 擴充。
- **稽核記錄**：每次 kill 的申請、執行、中止都會寫進 `deviceon_mcp.audit` logger（輸出到 stderr）。DeviceOn 端也會留下 `SetKillPrc` 操作事件。
- **權限**：使用 DeviceOn 帳號呼叫 API，沿用 DeviceOn 原本的角色和裝置群組權限。建議建立專用的服務帳號，只授予 `GetData`、`GetSensor`（`intermittent_report` 需要）、`GetProcess`、`EditProcess` 權限，以及目標裝置群組。

## 程式結構

```
src/deviceon_mcp/
├── server.py           # 入口：建立 FastMCP、依 DEVICEON_TOOLSETS 註冊工具、stdio / HTTP
├── config.py           # 環境變數設定、保護清單
├── client.py           # DeviceOn REST client（Basic / Bearer）
├── senml.py            # 解析 DeviceOn 的 {"bn", "e": [{"n","v"}]} 資料格式
├── analysis.py         # 週期偵測、相關係數（純 Python）
├── confirm_store.py    # 一次性確認 token
├── deps.py             # 共用依賴（client、clock、sleep，方便測試注入）
└── tools/
    ├── __init__.py     # TOOLSETS 註冊表
    ├── common/         # list_devices
    └── diagnose/       # metrics.py、processes.py
simulator/
├── windows/            # cpu_hog.exe（C#，build.bat 以內建 .NET Framework 4 編譯）
├── windows-task/       # mem_leak.exe + install.ps1 / uninstall.ps1（工作排程器觸發的記憶體暴增）
└── stress_sim.py       # Linux 用的 Python 版
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
Windows 使用者環境變數 ──(Claude Code 啟動時展開 ${VAR})──▶ .mcp.json 的 env ──▶ deviceon-mcp.exe 子程序
```

**步驟 1：設定使用者環境變數（每位成員做一次）**

```powershell
setx DEVICEON_BASE_URL "https://deviceon.wise-paas.com/rmm"
setx DEVICEON_USERNAME "root@advantech.com.tw"
setx DEVICEON_PASSWORD "2022AdvP@ssw0rd"
# 選用：venv 不在預設路徑 E:/workspace/DeviceOn/Backend/mcp-server 時才需要
setx DEVICEON_MCP_EXE "E:/workspace/DeviceOn/Backend/mcp-server/.venv/Scripts/deviceon-mcp.exe"
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
      "command": "${DEVICEON_MCP_EXE:-E:/workspace/DeviceOn/Backend/mcp-server/.venv/Scripts/deviceon-mcp.exe}",
      "args": [],
      "env": {
        "DEVICEON_BASE_URL": "${DEVICEON_BASE_URL}",
        "DEVICEON_USERNAME": "${DEVICEON_USERNAME}",
        "DEVICEON_PASSWORD": "${DEVICEON_PASSWORD}",
        "DEVICEON_TOOLSETS": "common,diagnose"
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
      "mcp__deviceon__request_kill_process"
    ],
    "ask": [
      "mcp__deviceon__confirm_kill_process"
    ]
  },
  "env": {
    "MCP_TOOL_TIMEOUT": "660000"
  }
}
```

- 讀取類工具自動放行，Demo 時不會一直跳出確認視窗。
- `confirm_kill_process` 一律詢問：就算 Agent 誤以為使用者已經同意，Claude Code 也會再跳出確認視窗。加上 server 端的 token 機制，總共有兩道關卡。
- `MCP_TOOL_TIMEOUT`（毫秒）：`capture_top_processes` 最長會執行 600 秒，設為 11 分鐘可以避免工具執行到一半被中斷。

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
| command | `E:/workspace/DeviceOn/Backend/mcp-server/.venv/Scripts/deviceon-mcp.exe` |
| args | （無） |
| env | `DEVICEON_BASE_URL`、`DEVICEON_USERNAME` / `DEVICEON_PASSWORD`（或 `DEVICEON_TOKEN`）、`DEVICEON_TOOLSETS` |

帳號資訊沿用 Claude Code 那一節設定的 Windows 使用者環境變數：如果 OpenClaw 的設定支援 `${VAR}` 展開，或啟動子程序時會繼承環境變數，設定檔裡就不需要寫密碼。如果都不支援，才把值直接寫進 OpenClaw 的設定，並確保那個檔案不會進版控。

如果 OpenClaw 接受常見的 `mcpServers` JSON 格式（以直接寫值為例）：

```json
{
  "mcpServers": {
    "deviceon": {
      "command": "E:/workspace/DeviceOn/Backend/mcp-server/.venv/Scripts/deviceon-mcp.exe",
      "args": [],
      "env": {
        "DEVICEON_BASE_URL": "https://<DeviceOn主機>/rmm",
        "DEVICEON_USERNAME": "mcp-agent@example.com",
        "DEVICEON_PASSWORD": "<密碼>",
        "DEVICEON_TOOLSETS": "common,diagnose"
      }
    }
  }
}
```

**Streamable HTTP（OpenClaw 在另一台機器）**：見下方 [HTTP 模式](#選用http-模式)，連線網址為 `http://<主機>:8765/mcp`。

**在 OpenClaw 端務必確認：**

1. **工具呼叫的 timeout 至少 11 分鐘**，否則 `capture_top_processes` 會被中斷。
2. **`confirm_kill_process` 需要人工核准。** 如果 OpenClaw 支援依工具設定核准規則，請對這個工具開啟。如果不支援，就只剩 server 端的兩段式 token 這一道關卡；server 的 `instructions` 和工具描述都有要求 Agent 先詢問使用者，但這只靠模型自律。
3. **依 ServerClaw 的工單類型選擇 toolset**：每種工單用不同的 `DEVICEON_TOOLSETS` 設定啟動（例如診斷工單用 `common,diagnose`）。

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

- **重新安裝之前，先關掉使用中的 Agent session。** server 執行中時 `deviceon-mcp.exe` 會被佔用，`pip install -e` 會因為無法覆寫檔案而失敗。只改 `.py` 檔沒有這個問題。
- **查看 server 的 log**：用 `claude --debug` 啟動 Claude Code，MCP Server 的 stderr 會一起顯示。也可以在終端機直接執行 `deviceon-mcp.exe`，看啟動時的錯誤訊息。
- **確認 token 存在記憶體中**，重新連線後會全部失效。如果在 `request_kill_process` 之後才重新連線，要重新申請 token。

## 疑難排解

| 現象 | 可能原因 | 處理方式 |
|---|---|---|
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
   `list_devices` → `analyze_metric_periodicity`（periodic=true, period≈180s）→ `capture_top_processes`（duration ≥ 180s，suspect=cpu_hog）→ `request_kill_process` → **Agent 詢問使用者** → `confirm_kill_process` → 等一個週期後再跑 `analyze_metric_periodicity` 確認尖峰已消失。

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
- **偵測**：讓 `usagePhysMem` 存入歷史資料，請 Agent 用 `analyze_metric_periodicity`，sensor 為 `ProcessMonitor:/System Monitor Info/usagePhysMem`。
- **現有工具的限制**：`capture_top_processes` 目前只用 CPU 的相關性找元兇。它的輸出也不含各 process 的記憶體用量。記憶體情境的 CPU 很低，所以現有工具**能偵測到週期性，但無法指出 `mem_leak.exe`**。要完整支援這個情境，需要在 MCP Server 加入以記憶體為依據的定位功能。

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
