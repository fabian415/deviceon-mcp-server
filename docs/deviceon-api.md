# DeviceOn Portal REST API 分類表

由 `WebApp/src/main/java` 的 JAX-RS 註解（`@Path`、`@GET` 等）自動整理，略過註解掉的舊 endpoint。
所有 REST 路徑都在 `ApplicationPath("rmm")` 底下，完整網址是 `https://<host>/rmm` + 下表路徑。
共 650 個 REST endpoint、59 個 resource class，另有 7 個 WebSocket endpoint（不在 `/rmm` 底下）。

「權限」欄是方法內出現的 `ModuleType.*`，是靜態掃描的結果，僅供參考；空白表示沒有找到（可能是不檢查權限，或在共用 helper 裡檢查）。

## 總覽

| 分類 | 說明 | Resource class（路徑前綴） | 數量 | GET | POST | PUT | PATCH | DELETE |
|---|---|---|---:|---:|---:|---:|---:|---:|
| [帳號與權限](#帳號與權限) | 登入、帳號、角色、SSO | AccountMgmt（`/v1/accounts`）<br>RoleMgmt（`/v1/roles`）<br>SSOMgmt（`/v1/sso`） | 47 | 26 | 7 | 1 | 8 | 5 |
| [裝置與群組](#裝置與群組) | 裝置清單與屬性、裝置群組、地圖、IoT 裝置、虛擬參數 | DeviceMgmt（`/v1/devices`）<br>DeviceGroupMgmt（`/v1/devicegroups`）<br>DeviceMapMgmt（`/v1/devicemap`）<br>IotDeviceMgmt（`/v1/iot-devices`）<br>VirtualParamMgmt（`/v1/virtual`） | 67 | 40 | 7 | 3 | 10 | 7 |
| [資料與事件](#資料與事件) | 即時／歷史資料、事件、操作記錄、Grafana SimpleJSON、MongoDB 維護 | DataMgmt（`/v1/data`）<br>EventMgmt（`/v1/events`）<br>LogMgmt（`/v1/logs`）<br>DataSJMgmt（`/v1/grafana/simplejson`）<br>EventSJMgmt（`/v1/grafana/simplejson/events`）<br>MongoMgmt（`/v1/db/nosql/mongo`） | 48 | 32 | 14 |  |  | 2 |
| [裝置控制](#裝置控制) | 感測器讀寫、電源、process、截圖、KVM、裝置 log、檔案同步、看門狗、熱插拔、DASH | DeviceCtrl（`/v1/devicectrl`）<br>PowerCtrl（`/v1/power`）<br>ProcessCtrl（`/v1/processes`）<br>ScreenshotCtrl（`/v1/screenshot`）<br>KVMMgmt（`/v1/kvm`）<br>DeviceLogCtrl（`/v1/devlog`）<br>FileSyncCtrl（`/v1/filesync`）<br>SoftwareWatchdogMgmt（`/v1/dog`）<br>HotSwapMgmt（`/v1/hotswap`）<br>DashCtrl（`/v1/dash`） | 42 | 21 | 7 | 9 | 2 | 3 |
| [保護與還原](#保護與還原) | 系統保護（寫入保護）與備份還原 | ProtectionMgmt（`/v1/protection`）<br>RecoveryMgmt（`/v1/recovery`） | 23 | 15 |  | 8 |  |  |
| [頻外管理（OOB）](#頻外管理oob) | IPMI、iBMC、Intel AMT／Open AMT、EdgeBMC | IPMICtrl（`/v1/ipmi`）<br>IbmcCtrl（`/v1/ibmc`）<br>iAMTCtrl（`/v1/iamt`）<br>OpenAMTCtrl（`/v1/oamt`）<br>EdgeBmcMgmt（`/v1/edgebmc/ctrl`）<br>EdgeBmcNodeMgmt（`/v1/edgebmc/node`）<br>EdgeBmcNodeV2Mgmt（`/v2/edgebmc/node`） | 75 | 32 | 28 | 7 | 4 | 4 |
| [OTA](#ota) | 套件、儲存庫、升級工作、排程、OTA 裝置（路徑沒有 v1） | RPackageController（`/packagecontrol`）<br>RStorageManager（`/storagemanager`）<br>RUpgradeController（`/upgradecontrol`）<br>RScheduleController（`/schedulecontrol`）<br>RDeviceManager（`/otadevicemanager`） | 116 | 72 | 24 | 1 | 4 | 15 |
| [容器與邊緣應用](#容器與邊緣應用) | Docker、ROS、異常偵測（ADS） | DockerMgmt（`/v1/docker`）<br>RosMgmt（`/v1/ros`）<br>ADSMgmt（`/v1/ads`） | 68 | 28 | 29 |  | 4 | 7 |
| [自動化與通知](#自動化與通知) | 規則、規則引擎、動作、排程、通知 | RuleMgmt（`/v1/rules`）<br>RuleEngineMgmt（`/v1/rule-engines`）<br>ActionMgmt（`/v1/action`）<br>ScheduleMgmt（`/v1/schedules`）<br>NotifyMgmt（`/v1/notifymgmt`） | 61 | 24 | 19 | 10 | 1 | 7 |
| [系統與整合](#系統與整合) | 系統資訊、設定、授權、Proxy、上下游伺服器路由、IoT Hub、Management Portal、內部 URL | SystemMgmt（`/v1/system`）<br>SettingMgmt（`/v1/settings`）<br>LicenseMgmt（`/v1/license`）<br>AppMgmt（`/v1/appinfo`）<br>ProxyMgmt（`/v1/proxy`）<br>RouteMgmt（`/v1/route`）<br>ServiceMgmt（`/v1/iothub`）<br>MPMgmt（`/v1/mp`）<br>InternalMgmt（`/v1/internal`） | 84 | 44 | 12 | 6 | 19 | 3 |
| [前端設定](#前端設定) | Dashboard、版面、UI 與 plugin 設定 | DashboardMgmt（`/v1/dashboard`）<br>LayoutMgmt（`/v1/layout`）<br>UiConfigMgmt（`/v1/ui-config`）<br>PluginConfigMgmt（`/v1/plugin-config`） | 19 | 6 | 3 | 4 | 1 | 5 |
| WebSocket | 終端機、即時資料、事件推送等 | 見[下方](#websocket) | 7 | | | | | |

## 帳號與權限

登入、帳號、角色、SSO

### AccountMgmt — `/v1/accounts`

原始碼：[AccountMgmt.java](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/accounts` | [getAccountsWithoutMentee](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2049) | GetAccount |
| POST | `/v1/accounts` | [addAccount](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L827) | AddAccount |
| PUT | `/v1/accounts` | [editAccount](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1148) | EditAccount |
| POST | `/v1/accounts/2fa/pause` | [pause2FA](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1082) |  |
| GET | `/v1/accounts/2fa/pause/verify` | [verifyPause2FA](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1906) |  |
| GET | `/v1/accounts/channel/messages` | [getChannelMessage](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2290) | GetAccount |
| GET | `/v1/accounts/groups/basics` | [getLittleGroups](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2580) | GetAccount |
| GET | `/v1/accounts/login` | [Login](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2439) |  |
| GET | `/v1/accounts/login/2fa` | [login2FA](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2462) |  |
| DELETE | `/v1/accounts/login/2fa` | [login2FA](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2762) |  |
| GET | `/v1/accounts/login/2fa/secret` | [get2FASecretKey](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2485) |  |
| POST | `/v1/accounts/logout` | [Logout](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L961) |  |
| GET | `/v1/accounts/myself` | [getAccount](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2317) | GetAccount |
| PATCH | `/v1/accounts/myself/password` | [editMyAccountPassword](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1477) |  |
| GET | `/v1/accounts/number` | [getAccountNum](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2208) | GetAccount |
| PATCH | `/v1/accounts/password` | [editAccountPassword](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1567) | EditAccount |
| DELETE | `/v1/accounts/password` | [resetAccountPassword](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2672) |  |
| PATCH | `/v1/accounts/privileges` | [editAccountPrivilege](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1672) | EditAccount |
| GET | `/v1/accounts/refresh/{token}` | [refreshToken](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2408) |  |
| POST | `/v1/accounts/signup` | [registerAccount](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L986) |  |
| GET | `/v1/accounts/signup/iotkey` | [getIoTKey](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2090) |  |
| GET | `/v1/accounts/signup/verify` | [verifyAccountRegistration](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1978) |  |
| GET | `/v1/accounts/token/validity` | [getAuth](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2604) |  |
| PATCH | `/v1/accounts/trial` | [editAccountTrial](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1356) | EditAccount, EditServiceKey |
| PATCH | `/v1/accounts/trial/days` | [editAccountTrialDays](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L1763) | EditAccount, EditServiceKey |
| GET | `/v1/accounts/{aid}` | [getAccount](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2236) | GetAccount |
| DELETE | `/v1/accounts/{aid}` | [deleteAccount](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2637) |  |
| GET | `/v1/accounts/{aid}/groups` | [getGroups](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2515) | GetAccount |
| DELETE | `/v1/accounts/{aid}/lock` | [unlockAccount](../../WebApp/src/main/java/com/rest/account/AccountMgmt.java#L2790) |  |

### RoleMgmt — `/v1/roles`

原始碼：[RoleMgmt.java](../../WebApp/src/main/java/com/rest/account/RoleMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/roles` | [getRoles](../../WebApp/src/main/java/com/rest/account/RoleMgmt.java#L303) | GetRole |
| GET | `/v1/roles/number` | [getRoleNum](../../WebApp/src/main/java/com/rest/account/RoleMgmt.java#L225) | GetRole |
| GET | `/v1/roles/{rid}` | [getRole](../../WebApp/src/main/java/com/rest/account/RoleMgmt.java#L341) | GetRole |
| GET | `/v1/roles/{rid}/accounts` | [getAccountListByRole](../../WebApp/src/main/java/com/rest/account/RoleMgmt.java#L378) | GetRole |
| GET | `/v1/roles/{rid}/accounts/number` | [getAccountNumByRole](../../WebApp/src/main/java/com/rest/account/RoleMgmt.java#L253) | GetRole |
| GET | `/v1/roles/{rid}/privileges` | [getPrivileges](../../WebApp/src/main/java/com/rest/account/RoleMgmt.java#L442) | GetRole |

### SSOMgmt — `/v1/sso`

原始碼：[SSOMgmt.java](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| PATCH | `/v1/sso/activation/users/{username}/password` | [patchUserPasswordByActCode](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L1159) |  |
| POST | `/v1/sso/login` | [SSOLogin](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L506) |  |
| POST | `/v1/sso/login/demo` | [SSOLoginDemo](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L597) |  |
| GET | `/v1/sso/logout` | [SSOLogout](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L866) |  |
| GET | `/v1/sso/remote_url` | [getHostUrl](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L769) |  |
| GET | `/v1/sso/scopes` | [getScopes](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L642) |  |
| POST | `/v1/sso/user` | [postUser](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L459) |  |
| GET | `/v1/sso/users` | [getUsers](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L672) |  |
| PATCH | `/v1/sso/users/{username}/password` | [patchUserPassword](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L1103) |  |
| DELETE | `/v1/sso/users/{username}/password` | [deleteUserPassword](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L1218) |  |
| GET | `/v1/sso/users/{username}/pwdresetemail` | [getPWResetMail](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L783) |  |
| PATCH | `/v1/sso/users/{username}/scopes` | [patchUser](../../WebApp/src/main/java/com/rest/sso/SSOMgmt.java#L919) |  |

## 裝置與群組

裝置清單與屬性、裝置群組、地圖、IoT 裝置、虛擬參數

### DeviceMgmt — `/v1/devices`

原始碼：[DeviceMgmt.java](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/devices` | [getDevice](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L535) | GetDevice |
| PATCH | `/v1/devices` | [editMatch](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1980) | EditDevice |
| GET | `/v1/devices/belongings` | [getBelongings](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1272) | GetDevice |
| POST | `/v1/devices/certificates` | [downloadCertificates](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L2951) | AddDeviceCert, GetDeviceCert |
| DELETE | `/v1/devices/connection/{agentId}` | [dropConnection](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L3293) |  |
| GET | `/v1/devices/connectivity` | [getDeviceNumberByConnectivity](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L873) | GetDevice |
| PATCH | `/v1/devices/coordinates` | [editCoordinate](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L2527) | EditDevice |
| DELETE | `/v1/devices/decommission/{agentId}` | [decommission](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L3346) |  |
| GET | `/v1/devices/embddc` | [getEmbDDC](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1868) |  |
| PUT | `/v1/devices/embddc` | [putEmbDDC](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L3005) |  |
| PATCH | `/v1/devices/grafana/templates` | [editGrafana](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L2653) | EditDevice |
| POST | `/v1/devices/import/csv` | [importDevices](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L2911) | AddDevGroup, EditDevice |
| PATCH | `/v1/devices/name/{agent_id}` | [renameDevice](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L2784) | EditDevice |
| GET | `/v1/devices/number/assigned/overall` | [getOverview](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L437) |  |
| GET | `/v1/devices/own/status/number` | [getOwnDeviceStatusNumber](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L768) | GetDevice |
| GET | `/v1/devices/own/status/statistics` | [getOwnDeviceStatisticsNumber](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L799) | GetDevice |
| GET | `/v1/devices/plugins` | [getPlugins](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1104) | GetDevice |
| GET | `/v1/devices/sensors` | [getSensors](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1168) | GetDevice |
| GET | `/v1/devices/statistics/abnormal-system-voltage` | [getAbnormalSystemVoltage](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1547) |  |
| GET | `/v1/devices/statistics/daily-sq-data-vol` | [getDailyDataVolume](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1797) |  |
| GET | `/v1/devices/statistics/group-v` | [groupingBy](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1740) |  |
| GET | `/v1/devices/statistics/ram-spd-lock` | [getRamSpdLock](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1579) |  |
| GET | `/v1/devices/statistics/ssd-opal` | [getSsdOpal](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1609) |  |
| GET | `/v1/devices/statistics/virus-pattern` | [getVirusPattern](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1639) |  |
| GET | `/v1/devices/statistics/wol-mode` | [getDeviceWolInfo](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1507) | GetDevice |
| GET | `/v1/devices/tags` | [getTags](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1398) | GetDevice |
| GET | `/v1/devices/topn` | [getTopN](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1319) |  |
| GET | `/v1/devices/unassigned` | [getUnAssignedDevices](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L692) |  |
| GET | `/v1/devices/unassigned/device` | [getUnAssignedDevice](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L731) |  |
| GET | `/v1/devices/unassigned/number` | [getUnAssignedDeviceNumber](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L667) | GetDevice |
| GET | `/v1/devices/upgradable` | [getUpgradableDevices](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L588) |  |
| GET | `/v1/devices/upgrade-info/{agentId}` | [getDeviceUpgradeInfo](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L1461) | GetDevice |
| PATCH | `/v1/devices/wol` | [editWOL](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L2350) | EditDevice |
| GET | `/v1/devices/{did}` | [getDevice](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L482) | GetDevice |
| GET | `/v1/devices/{did}/plugins` | [getPlugins](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L924) | GetDevice |
| GET | `/v1/devices/{did}/{plugin}/sensors` | [getSensors](../../WebApp/src/main/java/com/rest/device/DeviceMgmt.java#L994) | GetDevice |

### DeviceGroupMgmt — `/v1/devicegroups`

原始碼：[DeviceGroupMgmt.java](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/devicegroups` | [getDeviceGroups](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1080) | GetDevGroup |
| POST | `/v1/devicegroups` | [addDevGroup](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L560) | AddDevGroup |
| PUT | `/v1/devicegroups` | [editDeviceGroup](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L780) | EditDevGroup |
| GET | `/v1/devicegroups/devices` | [getAllGroupDevice](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1336) | GetDevGroup |
| GET | `/v1/devicegroups/devices/export` | [exportAllGroupDevice](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1437) | GetDevGroup |
| GET | `/v1/devicegroups/fields/filterable` | [getFilterableFields](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1323) |  |
| GET | `/v1/devicegroups/{gid}` | [getDeviceGroup](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1120) | GetDevGroup |
| DELETE | `/v1/devicegroups/{gid}` | [delDeviceGroup](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1756) | DeleteDevGroup |
| GET | `/v1/devicegroups/{gid}/devices` | [getGroupDevice](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1172) | GetDevGroup |
| GET | `/v1/devicegroups/{gid}/devices/export` | [exportGroupDevice](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1253) | GetDevGroup |
| GET | `/v1/devicegroups/{gid}/devices/number` | [getGroupDeviceNum](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1527) | GetDevGroup |
| GET | `/v1/devicegroups/{gid}/sq-info` | [getGroupSQInfo](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1597) |  |
| GET | `/v1/devicegroups/{gid}/{plugin}/sensors` | [getSensors](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1650) | GetDevGroup, GetDevice |
| DELETE | `/v1/devicegroups/{groupId}/coManaged` | [removeCoManage](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1886) | EditDevGroup |
| PATCH | `/v1/devicegroups/{groupId}/coManagedBy/{coManagerId}` | [addCoManage](../../WebApp/src/main/java/com/rest/device/DeviceGroupMgmt.java#L1940) | EditDevGroup |

### DeviceMapMgmt — `/v1/devicemap`

原始碼：[DeviceMapMgmt.java](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| PATCH | `/v1/devicemap/agent/{agentId}` | [updateDevice](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L805) | EditDevice |
| GET | `/v1/devicemap/building` | [getBuilding](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L1004) | GetDeviceMap |
| POST | `/v1/devicemap/building` | [addBuilding](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L406) | AddDeviceMap |
| PATCH | `/v1/devicemap/building/{mapId}` | [updateBuilding](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L691) | EditDeviceMap |
| POST | `/v1/devicemap/device` | [addDevice](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L546) | EditDevice |
| PATCH | `/v1/devicemap/device/{mapId}` | [updateDevice](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L878) | EditDevice |
| POST | `/v1/devicemap/plan` | [addPlan](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L475) | AddDeviceMap |
| PATCH | `/v1/devicemap/plan/{mapId}` | [updatePlan](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L749) | EditDeviceMap |
| GET | `/v1/devicemap/{mapId}` | [getMap](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L950) | GetDevice, GetDeviceMap |
| DELETE | `/v1/devicemap/{mapId}` | [deleteMap](../../WebApp/src/main/java/com/rest/devicemap/DeviceMapMgmt.java#L610) | DeleteDeviceMap, EditDevice |

### IotDeviceMgmt — `/v1/iot-devices`

原始碼：[IotDeviceMgmt.java](../../WebApp/src/main/java/com/rest/iotdevice/IotDeviceMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/iot-devices` | [getIotDevices](../../WebApp/src/main/java/com/rest/iotdevice/IotDeviceMgmt.java#L55) | GetIotDevice |
| POST | `/v1/iot-devices/register` | [regIotDevice](../../WebApp/src/main/java/com/rest/iotdevice/IotDeviceMgmt.java#L102) | EditIotDevice |
| DELETE | `/v1/iot-devices/{agentId}` | [delIotDevice](../../WebApp/src/main/java/com/rest/iotdevice/IotDeviceMgmt.java#L204) | DeleteIotDevice |

### VirtualParamMgmt — `/v1/virtual`

原始碼：[VirtualParamMgmt.java](../../WebApp/src/main/java/com/rest/virtual/VirtualParamMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/virtual/param` | [getParam](../../WebApp/src/main/java/com/rest/virtual/VirtualParamMgmt.java#L44) | GetVirtualParam |
| PUT | `/v1/virtual/param` | [setParam](../../WebApp/src/main/java/com/rest/virtual/VirtualParamMgmt.java#L91) | AddVirtualParam, EditVirtualParam |
| DELETE | `/v1/virtual/param` | [delParam](../../WebApp/src/main/java/com/rest/virtual/VirtualParamMgmt.java#L152) | DeleteVirtualParam |

## 資料與事件

即時／歷史資料、事件、操作記錄、Grafana SimpleJSON、MongoDB 維護

### DataMgmt — `/v1/data`

原始碼：[DataMgmt.java](../../WebApp/src/main/java/com/rest/data/DataMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| DELETE | `/v1/data` | [delDeviceData](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L3398) | DeleteSensor |
| GET | `/v1/data/devices/capability` | [getCapability](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L3062) | GetData |
| GET | `/v1/data/devices/histdata` | [getHistData](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L2176) | GetData |
| GET | `/v1/data/devices/histdata/delimited` | [getHistDistData](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L1935) | GetData |
| GET | `/v1/data/devices/histdata_by_opts` | [getHistDataByOpTS](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L2739) | GetData |
| GET | `/v1/data/devices/latestdata` | [getLatestData](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L1772) | GetData |
| GET | `/v1/data/devices/latestdata_by_opts` | [getLatestDataByOpTS](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L2441) | GetData |
| GET | `/v1/data/devices/reportplugins` | [getReportPlugin](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L3140) | GetData |
| GET | `/v1/data/devices/rule_actions` | [getRuleActions](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L1505) | GetData |
| GET | `/v1/data/devices/sensorinfos` | [getSensorInfo](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L3192) | GetData |
| GET | `/v1/data/devices/{did}/capability` | [getCapability](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L1613) | GetData |
| GET | `/v1/data/devices/{did}/histdata` | [getHistData](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L757) | GetData |
| GET | `/v1/data/devices/{did}/histdata/delimited` | [getHistDistData](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L518) | GetData |
| GET | `/v1/data/devices/{did}/histdata_by_opts` | [getHistDataByOpTS](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L1208) | GetData |
| GET | `/v1/data/devices/{did}/latestdata` | [getLatestData](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L338) | GetData |
| GET | `/v1/data/devices/{did}/latestdata_by_opts` | [getLatestDataByOpTS](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L1031) | GetData |
| GET | `/v1/data/groups/reportplugins` | [getReportPlugin](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L3269) | GetData |
| GET | `/v1/data/groups/sensorinfos` | [getSensorInfo](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L3321) | GetData |
| GET | `/v1/data/timeseries` | [getTimeSeriesForTopN](../../WebApp/src/main/java/com/rest/data/DataMgmt.java#L1691) | GetData |

### EventMgmt — `/v1/events`

原始碼：[EventMgmt.java](../../WebApp/src/main/java/com/rest/event/EventMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| DELETE | `/v1/events` | [deleteEvents](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L2876) | DeleteEvent |
| GET | `/v1/events/devicegroup/{groupId}/last` | [getDeviceGroupLastEvent](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L168) | GetEvent |
| GET | `/v1/events/devices` | [getDeviceEvents](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L592) | GetEvent |
| GET | `/v1/events/devices/export` | [exportDeviceEvents](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L1785) | GetEvent |
| GET | `/v1/events/operation` | [getOperationEvents](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L970) | GetEvent |
| GET | `/v1/events/operation/export` | [exportOperationEvents](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L2121) | GetEvent |
| GET | `/v1/events/statistics/account` | [getStatisticsAccount](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L330) | GetEvent |
| GET | `/v1/events/statistics/device` | [getStatisticsDevice](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L447) | GetEvent |
| GET | `/v1/events/statistics/type` | [getStatisticsType](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L227) | GetEvent |
| GET | `/v1/events/system` | [getSystemEvents](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L1381) | GetEvent |
| GET | `/v1/events/system/export` | [exportSystemEvents](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L2504) | GetEvent |
| GET | `/v1/events/system_monitor` | [getDeviceEvents](../../WebApp/src/main/java/com/rest/event/EventMgmt.java#L548) |  |

### LogMgmt — `/v1/logs`

原始碼：[LogMgmt.java](../../WebApp/src/main/java/com/rest/log/LogMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/logs/recent` | [getRecentLogs](../../WebApp/src/main/java/com/rest/log/LogMgmt.java#L37) |  |

### DataSJMgmt — `/v1/grafana/simplejson`

原始碼：[DataSJMgmt.java](../../WebApp/src/main/java/com/rest/grafana/DataSJMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/grafana/simplejson` | [testConnection](../../WebApp/src/main/java/com/rest/grafana/DataSJMgmt.java#L301) |  |
| POST | `/v1/grafana/simplejson/auth` | [getToken](../../WebApp/src/main/java/com/rest/grafana/DataSJMgmt.java#L605) |  |
| POST | `/v1/grafana/simplejson/devices` | [getDevcies](../../WebApp/src/main/java/com/rest/grafana/DataSJMgmt.java#L421) | GetDevice |
| POST | `/v1/grafana/simplejson/plugins` | [getPlugins](../../WebApp/src/main/java/com/rest/grafana/DataSJMgmt.java#L454) | GetDevice |
| POST | `/v1/grafana/simplejson/query` | [query](../../WebApp/src/main/java/com/rest/grafana/DataSJMgmt.java#L315) | GetData |
| POST | `/v1/grafana/simplejson/sensors` | [getSensors](../../WebApp/src/main/java/com/rest/grafana/DataSJMgmt.java#L512) | GetDevice |
| POST | `/v1/grafana/simplejson/setValues` | [setValues](../../WebApp/src/main/java/com/rest/grafana/DataSJMgmt.java#L650) | EditSensor |

### EventSJMgmt — `/v1/grafana/simplejson/events`

原始碼：[EventSJMgmt.java](../../WebApp/src/main/java/com/rest/grafana/EventSJMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/grafana/simplejson/events` | [testConnection](../../WebApp/src/main/java/com/rest/grafana/EventSJMgmt.java#L329) |  |
| POST | `/v1/grafana/simplejson/events/accounts` | [getAccounts](../../WebApp/src/main/java/com/rest/grafana/EventSJMgmt.java#L416) | GetAccount |
| POST | `/v1/grafana/simplejson/events/auth` | [getToken](../../WebApp/src/main/java/com/rest/grafana/EventSJMgmt.java#L674) |  |
| POST | `/v1/grafana/simplejson/events/devices` | [getDevcies](../../WebApp/src/main/java/com/rest/grafana/EventSJMgmt.java#L454) | GetDevice |
| POST | `/v1/grafana/simplejson/events/groups` | [getGroups](../../WebApp/src/main/java/com/rest/grafana/EventSJMgmt.java#L376) | GetDevGroup |
| POST | `/v1/grafana/simplejson/events/query` | [query](../../WebApp/src/main/java/com/rest/grafana/EventSJMgmt.java#L487) | GetData |
| POST | `/v1/grafana/simplejson/events/types` | [getTypes](../../WebApp/src/main/java/com/rest/grafana/EventSJMgmt.java#L343) | GetDevGroup |

### MongoMgmt — `/v1/db/nosql/mongo`

原始碼：[MongoMgmt.java](../../WebApp/src/main/java/com/rest/db/nosql/MongoMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| POST | `/v1/db/nosql/mongo/convertToCapped` | [convertToCapped](../../WebApp/src/main/java/com/rest/db/nosql/MongoMgmt.java#L139) | EditNoSQL |
| POST | `/v1/db/nosql/mongo/indexes/opts` | [addIndex](../../WebApp/src/main/java/com/rest/db/nosql/MongoMgmt.java#L56) | AddAccount |

## 裝置控制

感測器讀寫、電源、process、截圖、KVM、裝置 log、檔案同步、看門狗、熱插拔、DASH

### DeviceCtrl — `/v1/devicectrl`

原始碼：[DeviceCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| PUT | `/v1/devicectrl/data` | [setSensorData](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L857) | EditSensor |
| GET | `/v1/devicectrl/devices/data` | [getSensorData](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L581) | GetSensor |
| GET | `/v1/devicectrl/devices/{did}/data` | [getSensorData](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L76) | GetSensor |
| PUT | `/v1/devicectrl/intermittent_report` | [startIntermittentReport](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L1194) | GetSensor |
| PUT | `/v1/devicectrl/periodic_report` | [startPeriodicReport](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L1420) | GetSensor |
| PATCH | `/v1/devicectrl/periodic_report/{agentId}` | [applyAutoReport](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L1841) | GetSensor |
| PUT | `/v1/devicectrl/report_suspension` | [stopPeriodicReport](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L1539) | GetSensor |
| GET | `/v1/devicectrl/selfweb` | [getSelfWebData](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L436) | GetSensor |
| POST | `/v1/devicectrl/selfweb` | [ctlSelfWeb](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceCtrl.java#L1680) | EditSensor, GetSensor |

### PowerCtrl — `/v1/power`

原始碼：[PowerCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/PowerCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| PUT | `/v1/power/device` | [DevicePowerOnOff](../../WebApp/src/main/java/com/rest/devctrl/v1/PowerCtrl.java#L580) | EditPower |
| GET | `/v1/power/devices` | [getPowerInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/PowerCtrl.java#L1123) | GetPower |
| GET | `/v1/power/devices/{did}` | [getPowerInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/PowerCtrl.java#L1036) | GetPower |
| PUT | `/v1/power/group` | [GroupPowerOnOff](../../WebApp/src/main/java/com/rest/devctrl/v1/PowerCtrl.java#L821) | EditPower |
| GET | `/v1/power/supported_poweron_modes` | [getPowerOnSupportMode](../../WebApp/src/main/java/com/rest/devctrl/v1/PowerCtrl.java#L1210) |  |

### ProcessCtrl — `/v1/processes`

原始碼：[ProcessCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/ProcessCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| POST | `/v1/processes` | [runProcess](../../WebApp/src/main/java/com/rest/devctrl/v1/ProcessCtrl.java#L373) | EditProcess |
| PUT | `/v1/processes` | [ctrlProcess](../../WebApp/src/main/java/com/rest/devctrl/v1/ProcessCtrl.java#L528) | EditProcess |
| GET | `/v1/processes/devices` | [getProcesses](../../WebApp/src/main/java/com/rest/devctrl/v1/ProcessCtrl.java#L901) | GetProcess |
| GET | `/v1/processes/devices/{did}` | [getProcesses](../../WebApp/src/main/java/com/rest/devctrl/v1/ProcessCtrl.java#L803) | GetProcess |

### ScreenshotCtrl — `/v1/screenshot`

原始碼：[ScreenshotCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/ScreenshotCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/screenshot` | [getScreenShot](../../WebApp/src/main/java/com/rest/devctrl/v1/ScreenshotCtrl.java#L93) | GetScreenShot |
| GET | `/v1/screenshot/devices` | [getScreenShot_D](../../WebApp/src/main/java/com/rest/devctrl/v1/ScreenshotCtrl.java#L485) | GetScreenShot |
| GET | `/v1/screenshot/devices/{did}` | [getScreenShot](../../WebApp/src/main/java/com/rest/devctrl/v1/ScreenshotCtrl.java#L306) | GetScreenShot |
| GET | `/v1/screenshot/group/{groupId}` | [groupScreenShot](../../WebApp/src/main/java/com/rest/devctrl/v1/ScreenshotCtrl.java#L129) | GetScreenShot |

### KVMMgmt — `/v1/kvm`

原始碼：[KVMMgmt.java](../../WebApp/src/main/java/com/rest/devctrl/v1/KVMMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| POST | `/v1/kvm` | [setKVMMode](../../WebApp/src/main/java/com/rest/devctrl/v1/KVMMgmt.java#L114) | GetKVM |
| POST | `/v1/kvm/file-transfer` | [fileTransfer](../../WebApp/src/main/java/com/rest/devctrl/v1/KVMMgmt.java#L324) | GetKVM |
| DELETE | `/v1/kvm/file-transfer` | [stopFileTransfer](../../WebApp/src/main/java/com/rest/devctrl/v1/KVMMgmt.java#L480) | GetKVM |
| GET | `/v1/kvm/file-transfer/ice-server` | [getStunServer](../../WebApp/src/main/java/com/rest/devctrl/v1/KVMMgmt.java#L78) | GetKVM |

### DeviceLogCtrl — `/v1/devlog`

原始碼：[DeviceLogCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceLogCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/devlog` | [getDeviceSyslog](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceLogCtrl.java#L221) | GetDeviceLog |
| GET | `/v1/devlog/requests` | [getLogDataRequests](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceLogCtrl.java#L269) | GetDeviceLog |
| POST | `/v1/devlog/requests` | [requestLogData](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceLogCtrl.java#L403) | GetDeviceLog |
| GET | `/v1/devlog/requests/{id}` | [getLogData](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceLogCtrl.java#L361) | GetDeviceLog |
| DELETE | `/v1/devlog/requests/{id}` | [cancel](../../WebApp/src/main/java/com/rest/devctrl/v1/DeviceLogCtrl.java#L531) | EditDeviceLog |

### FileSyncCtrl — `/v1/filesync`

原始碼：[FileSyncCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/FileSyncCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/filesync/{agentId}` | [getFileSync](../../WebApp/src/main/java/com/rest/devctrl/v1/FileSyncCtrl.java#L66) | GetFileSync |
| PUT | `/v1/filesync/{agentId}` | [editFileSync](../../WebApp/src/main/java/com/rest/devctrl/v1/FileSyncCtrl.java#L106) | EditFileSync |

### SoftwareWatchdogMgmt — `/v1/dog`

原始碼：[SoftwareWatchdogMgmt.java](../../WebApp/src/main/java/com/rest/softwarewatchdog/SoftwareWatchdogMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| PATCH | `/v1/dog/setting` | [addSetting](../../WebApp/src/main/java/com/rest/softwarewatchdog/SoftwareWatchdogMgmt.java#L244) | EditSoftwareWatchdog |
| DELETE | `/v1/dog/setting` | [delSetting](../../WebApp/src/main/java/com/rest/softwarewatchdog/SoftwareWatchdogMgmt.java#L323) | EditSoftwareWatchdog |
| GET | `/v1/dog/{agentId}` | [getDog](../../WebApp/src/main/java/com/rest/softwarewatchdog/SoftwareWatchdogMgmt.java#L81) | GetSoftwareWatchdog |
| PUT | `/v1/dog/{agentId}` | [editDog](../../WebApp/src/main/java/com/rest/softwarewatchdog/SoftwareWatchdogMgmt.java#L146) | EditSoftwareWatchdog |

### HotSwapMgmt — `/v1/hotswap`

原始碼：[HotSwapMgmt.java](../../WebApp/src/main/java/com/rest/hotswap/HotSwapMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/hotswap/{agentId}` | [getHotSwap](../../WebApp/src/main/java/com/rest/hotswap/HotSwapMgmt.java#L62) | GetHotSwap |
| GET | `/v1/hotswap/{agentId}/history` | [getHotSwapHistory](../../WebApp/src/main/java/com/rest/hotswap/HotSwapMgmt.java#L124) | GetHotSwap |
| POST | `/v1/hotswap/{agentId}/whitelist` | [resetHotSwapWhitelist](../../WebApp/src/main/java/com/rest/hotswap/HotSwapMgmt.java#L197) | EditHotSwap |

### DashCtrl — `/v1/dash`

原始碼：[DashCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/DashCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/dash/devices` | [getDASH](../../WebApp/src/main/java/com/rest/devctrl/v1/DashCtrl.java#L53) | GetDash |
| POST | `/v1/dash/devices` | [setDASH](../../WebApp/src/main/java/com/rest/devctrl/v1/DashCtrl.java#L102) | EditDash |

## 保護與還原

系統保護（寫入保護）與備份還原

### ProtectionMgmt — `/v1/protection`

原始碼：[ProtectionMgmt.java](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| PUT | `/v1/protection/device` | [DeviceProtection](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L375) | EditProtection |
| PUT | `/v1/protection/device_sn` | [DeviceProtectionWithSN](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L682) | EditProtection |
| GET | `/v1/protection/devices` | [getProtectionInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L1684) | GetProtection |
| GET | `/v1/protection/devices/own/status` | [getProtectionsInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L1844) | GetProtection |
| GET | `/v1/protection/devices/own/status/number` | [getProtectionStatusNumber](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L2144) | GetProtection |
| GET | `/v1/protection/devices/{did}` | [getProtectionInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L1595) | GetProtection |
| PUT | `/v1/protection/group` | [GroupProtection](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L1016) | EditProtection |
| PUT | `/v1/protection/group_sn` | [GroupProtectionWithSN](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L1289) | EditProtection |
| GET | `/v1/protection/groups/account/{aid}` | [getAccountProtectionsInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L1973) | GetProtection |
| GET | `/v1/protection/groups/{gid}` | [getProtectionsInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L1889) | GetProtection |
| GET | `/v1/protection/statistics/groups/{gid}` | [getStatisticProtectionInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/ProtectionMgmt.java#L2092) | GetProtection |

### RecoveryMgmt — `/v1/recovery`

原始碼：[RecoveryMgmt.java](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| PUT | `/v1/recovery/device` | [DeviceRecovery](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L297) | EditRecovery |
| PUT | `/v1/recovery/device_sn` | [DeviceRecoveryWithSN](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L632) | EditRecovery |
| GET | `/v1/recovery/devices` | [getRecoveryInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L1706) | GetRecovery |
| GET | `/v1/recovery/devices/own/status` | [getProtectionsInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L1907) | GetRecovery |
| GET | `/v1/recovery/devices/own/status/number` | [getRecoverieStatusNumber](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L2207) | GetRecovery |
| GET | `/v1/recovery/devices/remote/backup/{agentId}` | [getRecoveryInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L1781) | GetRecovery |
| GET | `/v1/recovery/devices/{did}` | [getRecoveryInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L1618) | GetRecovery |
| PUT | `/v1/recovery/group` | [GroupRecovery](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L996) | EditRecovery |
| PUT | `/v1/recovery/group_sn` | [GroupRecoveryWithSN](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L1290) | EditRecovery |
| GET | `/v1/recovery/groups/account/{aid}` | [getAccountRecoveriesInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L2036) | GetRecovery |
| GET | `/v1/recovery/groups/{gid}` | [getRecoveriesInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L1952) | GetRecovery |
| GET | `/v1/recovery/statistics/groups/{gid}` | [getStatisticRecoveryInfo](../../WebApp/src/main/java/com/rest/devctrl/v1/RecoveryMgmt.java#L2155) | GetRecovery |

## 頻外管理（OOB）

IPMI、iBMC、Intel AMT／Open AMT、EdgeBMC

### IPMICtrl — `/v1/ipmi`

原始碼：[IPMICtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/ipmi` | [getIPMIServers](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L173) | GetIPMIServer |
| POST | `/v1/ipmi` | [addIPMIServer](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L361) | AddIPMIServer |
| PATCH | `/v1/ipmi` | [editIPMIServer](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L458) | EditIPMIServer |
| GET | `/v1/ipmi/power` | [getPowerStatus](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L326) | GetIPMIServer |
| PUT | `/v1/ipmi/power/down/{serverId}` | [setPowerDown](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L439) |  |
| PUT | `/v1/ipmi/power/reset/{serverId}` | [setPowerReset](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L448) |  |
| PUT | `/v1/ipmi/power/up/{serverId}` | [setPowerUp](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L430) |  |
| GET | `/v1/ipmi/sel` | [getFirstSystemEventLog](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L267) | GetIPMIServer |
| GET | `/v1/ipmi/sensors` | [getIPMISensors](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L224) | GetIPMIServer |
| DELETE | `/v1/ipmi/{serverId}` | [deleteIPMIServer](../../WebApp/src/main/java/com/rest/devctrl/v1/IPMICtrl.java#L544) | DeleteIPMIServer |

### IbmcCtrl — `/v1/ibmc`

原始碼：[IbmcCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/IbmcCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| POST | `/v1/ibmc` | [ibmcPowerAction](../../WebApp/src/main/java/com/rest/devctrl/v1/IbmcCtrl.java#L709) | EditIBMC |
| POST | `/v1/ibmc/backup/{agentId}` | [ibmcBackup](../../WebApp/src/main/java/com/rest/devctrl/v1/IbmcCtrl.java#L895) | EditIBMC |
| GET | `/v1/ibmc/bios/bootup/handler/{agentId}` | [ibmcBootupHandler](../../WebApp/src/main/java/com/rest/devctrl/v1/IbmcCtrl.java#L580) | GetIBMC |
| GET | `/v1/ibmc/bios/bootup/{agentId}` | [ibmcBootupIndex](../../WebApp/src/main/java/com/rest/devctrl/v1/IbmcCtrl.java#L648) | GetIBMC |
| POST | `/v1/ibmc/bios/bootup/{agentId}/{index}` | [ibmcBootupIndex](../../WebApp/src/main/java/com/rest/devctrl/v1/IbmcCtrl.java#L821) | EditIBMC |
| POST | `/v1/ibmc/bios/ocr/{agentId}` | [ibmcOCR](../../WebApp/src/main/java/com/rest/devctrl/v1/IbmcCtrl.java#L761) | EditIBMC |
| POST | `/v1/ibmc/recovery/{agentId}` | [ibmcRecovery](../../WebApp/src/main/java/com/rest/devctrl/v1/IbmcCtrl.java#L965) | EditIBMC |

### iAMTCtrl — `/v1/iamt`

原始碼：[iAMTCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/iAMTCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| POST | `/v1/iamt/cl` | [genCredential](../../WebApp/src/main/java/com/rest/devctrl/v1/iAMTCtrl.java#L264) | GetIAMT |
| GET | `/v1/iamt/devices` | [getIAMT](../../WebApp/src/main/java/com/rest/devctrl/v1/iAMTCtrl.java#L71) | GetIAMT |
| POST | `/v1/iamt/devices` | [setIAMT](../../WebApp/src/main/java/com/rest/devctrl/v1/iAMTCtrl.java#L122) | EditIAMT |

### OpenAMTCtrl — `/v1/oamt`

原始碼：[OpenAMTCtrl.java](../../WebApp/src/main/java/com/rest/devctrl/v1/OpenAMTCtrl.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/oamt/devices` | [getOpenAMT](../../WebApp/src/main/java/com/rest/devctrl/v1/OpenAMTCtrl.java#L69) | GetOpenAMT |
| POST | `/v1/oamt/devices` | [setOpenAMT](../../WebApp/src/main/java/com/rest/devctrl/v1/OpenAMTCtrl.java#L198) | EditOpenAMT |
| PATCH | `/v1/oamt/devices` | [setDeviceGuid](../../WebApp/src/main/java/com/rest/devctrl/v1/OpenAMTCtrl.java#L404) | EditOpenAMT |
| GET | `/v1/oamt/devices/consent` | [getConsentCode](../../WebApp/src/main/java/com/rest/devctrl/v1/OpenAMTCtrl.java#L137) | GetOpenAMT |
| POST | `/v1/oamt/devices/consent` | [sendConsentCode](../../WebApp/src/main/java/com/rest/devctrl/v1/OpenAMTCtrl.java#L339) | GetOpenAMT |
| DELETE | `/v1/oamt/devices/consent` | [cancelConsentCode](../../WebApp/src/main/java/com/rest/devctrl/v1/OpenAMTCtrl.java#L459) | GetOpenAMT |

### EdgeBmcMgmt — `/v1/edgebmc/ctrl`

原始碼：[EdgeBmcMgmt.java](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/edgebmc/ctrl/cert` | [getCert](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1067) | GetEdgeBMC |
| POST | `/v1/edgebmc/ctrl/cert` | [uploadCertFile](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1100) | EditEdgeBMC |
| GET | `/v1/edgebmc/ctrl/cert/sample` | [downloadCertSampleFile](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1048) |  |
| PATCH | `/v1/edgebmc/ctrl/cert/{cid}` | [updateCert](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1206) | EditEdgeBMC |
| DELETE | `/v1/edgebmc/ctrl/cert/{cid}` | [deleteCert](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1259) | EditEdgeBMC |
| GET | `/v1/edgebmc/ctrl/customaction/{action}/info` | [getCustomActionInfo](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L478) | GetEdgeBMC |
| GET | `/v1/edgebmc/ctrl/dl/clearData/{id}` | [getEdgeBmcClearBin](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L160) |  |
| GET | `/v1/edgebmc/ctrl/dl/provData/{id}` | [getEdgeBmcProvisionBin](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L129) |  |
| GET | `/v1/edgebmc/ctrl/dl/provTool/{id}` | [getEdgeBmcProvisionTool](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L98) |  |
| GET | `/v1/edgebmc/ctrl/fw` | [getFirmware](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1310) | GetEdgeBMC |
| POST | `/v1/edgebmc/ctrl/fw` | [uploadFirmware](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1442) | EditEdgeBMC |
| GET | `/v1/edgebmc/ctrl/fw/option` | [getFirmwareOption](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1368) | GetEdgeBMC |
| GET | `/v1/edgebmc/ctrl/fw/target` | [getFirmwareTarget](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1339) | GetEdgeBMC |
| DELETE | `/v1/edgebmc/ctrl/fw/{fid}` | [deleteFirmware](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1611) | EditEdgeBMC |
| GET | `/v1/edgebmc/ctrl/fw/{fid}/manifest` | [downloadFirmwareManifestFile](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1405) | GetEdgeBMC |
| POST | `/v1/edgebmc/ctrl/fw/{fid}/signature` | [uploadFirmwareSignature](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L1533) | EditEdgeBMC |
| GET | `/v1/edgebmc/ctrl/node/{agentId}` | [getEdgeBmcInfo](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L194) | GetEdgeBMC |
| POST | `/v1/edgebmc/ctrl/node/{agentId}` | [engTestAgentJoin](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L758) | EditEdgeBMC |
| PATCH | `/v1/edgebmc/ctrl/node/{bmcAgentId}` | [updateEdgeBmcInfo](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L700) | EditEdgeBMC |
| POST | `/v1/edgebmc/ctrl/node/{bmcAgentId}/customaction` | [enableEdgeBmcCustomAction](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L973) | EditEdgeBMC |
| PUT | `/v1/edgebmc/ctrl/node/{bmcAgentId}/customaction` | [setEdgeBmcCustomAction](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L657) | EditEdgeBMC |
| GET | `/v1/edgebmc/ctrl/node/{bmcAgentId}/customaction/{action}/info` | [getEdgeBmcCustomActionInfo](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L435) | GetEdgeBMC |
| PUT | `/v1/edgebmc/ctrl/node/{bmcAgentId}/firmwareupdate` | [setFirmwareUpdate](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L620) | EditEdgeBMC |
| GET | `/v1/edgebmc/ctrl/node/{bmcAgentId}/health` | [getEdgeBmcHealth](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L223) | GetEdgeBMC |
| GET | `/v1/edgebmc/ctrl/node/{bmcAgentId}/info/firmwareupdate` | [getEdgeBmcFirmwareUpdate](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L388) | GetEdgeBMC |
| GET | `/v1/edgebmc/ctrl/node/{bmcAgentId}/info/powercycle` | [getEdgeBmcPowerCycle](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L296) | GetEdgeBMC |
| GET | `/v1/edgebmc/ctrl/node/{bmcAgentId}/info/target` | [getEdgeBmcTarget](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L341) | GetEdgeBMC |
| PUT | `/v1/edgebmc/ctrl/node/{bmcAgentId}/oneshotaction` | [setOneShotAction](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L516) | EditEdgeBMC |
| POST | `/v1/edgebmc/ctrl/node/{bmcAgentId}/oneshottask` | [setOneShotTask](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L826) | EditEdgeBMC |
| PUT | `/v1/edgebmc/ctrl/node/{bmcAgentId}/regularreport` | [setRegularReport](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L573) | EditEdgeBMC |
| POST | `/v1/edgebmc/ctrl/node/{bmcAgentId}/regularreporttasks` | [setRegularReportTask](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L900) | EditEdgeBMC |
| GET | `/v1/edgebmc/ctrl/node/{bmcAgentId}/sensor` | [getEdgeBmcSensor](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcMgmt.java#L252) | GetEdgeBMC |

### EdgeBmcNodeMgmt — `/v1/edgebmc/node`

原始碼：[EdgeBmcNodeMgmt.java](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| POST | `/v1/edgebmc/node/auth/{bmcAgentId}/challenge` | [nodeChallenge](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L1000) |  |
| GET | `/v1/edgebmc/node/file/{bmcAgentId}/download/{token}` | [downloadData](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L857) |  |
| GET | `/v1/edgebmc/node/file/{bmcAgentId}/manifest` | [downloadFirmwareManifest](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L800) |  |
| GET | `/v1/edgebmc/node/join/{bmcAgentId}` | [getJoinStatus](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L88) |  |
| POST | `/v1/edgebmc/node/join/{bmcAgentId}` | [joinExchangeKey](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L135) |  |
| POST | `/v1/edgebmc/node/join/{bmcAgentId}/credential` | [joinVerification](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L236) |  |
| POST | `/v1/edgebmc/node/polling/{bmcAgentId}/ability` | [setAbility](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L402) |  |
| POST | `/v1/edgebmc/node/polling/{bmcAgentId}/swinfo` | [setSoftwareInfo](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L315) |  |
| POST | `/v1/edgebmc/node/polling/{bmcAgentId}/tsksync` | [syncTask](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L465) |  |
| POST | `/v1/edgebmc/node/task/{bmcAgentId}/actsts` | [setActionStatus](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L656) |  |
| POST | `/v1/edgebmc/node/task/{bmcAgentId}/p80data` | [setP80Data](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L730) |  |
| POST | `/v1/edgebmc/node/task/{bmcAgentId}/rpt` | [writeSensorReport](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L591) |  |
| GET | `/v1/edgebmc/node/task/{bmcAgentId}/tskparam` | [getTaskParameter](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeMgmt.java#L547) |  |

### EdgeBmcNodeV2Mgmt — `/v2/edgebmc/node`

原始碼：[EdgeBmcNodeV2Mgmt.java](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeV2Mgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| POST | `/v2/edgebmc/node/polling/{bmcAgentId}/ability` | [setAbilityV2](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeV2Mgmt.java#L56) |  |
| POST | `/v2/edgebmc/node/task/{bmcAgentId}/actprogress` | [setCustomTaskProgress](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeV2Mgmt.java#L267) |  |
| GET | `/v2/edgebmc/node/task/{bmcAgentId}/custactparam` | [getCustomTaskParameter](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeV2Mgmt.java#L187) |  |
| GET | `/v2/edgebmc/node/task/{bmcAgentId}/tskparam` | [getTaskParameter](../../WebApp/src/main/java/com/rest/edgebmc/EdgeBmcNodeV2Mgmt.java#L150) |  |

## OTA

套件、儲存庫、升級工作、排程、OTA 裝置（路徑沒有 v1）

### RPackageController — `/packagecontrol`

原始碼：[RPackageController.java](../../WebApp/src/main/java/com/rest/ota/RPackageController.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| DELETE | `/packagecontrol/all/package` | [rDeleteAllPackages](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L487) |  |
| GET | `/packagecontrol/all/package/deletestatus` | [rGetAllDeleteStatus](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1086) |  |
| GET | `/packagecontrol/all/package/installable` | [rGetInstallablePackageType](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1153) |  |
| GET | `/packagecontrol/all/package/type` | [rGetAllPackageType](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1132) |  |
| GET | `/packagecontrol/all/package/uploadstatus` | [rGetAllUploadStatus](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L910) |  |
| GET | `/packagecontrol/byname/package` | [rGetPackageInfoByName](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L502) |  |
| DELETE | `/packagecontrol/byname/package` | [rDeletePackageByName](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L389) |  |
| GET | `/packagecontrol/byname/package/deletestatus` | [rGetDeleteStatusByName](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L956) |  |
| GET | `/packagecontrol/byname/package/uploadstatus` | [rGetUploadStatusByName](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L824) |  |
| GET | `/packagecontrol/bytype/new/package` | [rGetPackageInfosByTypeAndMultiStorageId](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L580) |  |
| GET | `/packagecontrol/bytype/package` | [rGetPackageInfosByType](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L550) |  |
| DELETE | `/packagecontrol/bytype/package` | [rDeletePackagesByType](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L464) |  |
| GET | `/packagecontrol/bytype/package/deletestatus` | [rGetDeleteStatusByType](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L999) |  |
| GET | `/packagecontrol/cluster/package` | [rGetAClusterPackageInfos](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L523) |  |
| DELETE | `/packagecontrol/cluster/package` | [rDeleteAClusterPackages](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L424) |  |
| GET | `/packagecontrol/cluster/package/category` | [rGetPackageCategoryList](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2344) |  |
| GET | `/packagecontrol/cluster/package/company` | [rFindPackageCompany](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2271) |  |
| GET | `/packagecontrol/cluster/package/deletestatus` | [rGetAClusterDeleteStatus](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1042) |  |
| GET | `/packagecontrol/cluster/package/detail` | [rFindPackageDetail](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1876) |  |
| GET | `/packagecontrol/cluster/package/uploadstatus` | [rGetAClusterUploadStatus](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L867) |  |
| GET | `/packagecontrol/contact` | [rFindContact](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2498) |  |
| POST | `/packagecontrol/contact` | [rAddContact](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2371) |  |
| PATCH | `/packagecontrol/contact` | [rUpdateContact](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2409) |  |
| DELETE | `/packagecontrol/contact` | [rDeleteContact](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2457) |  |
| POST | `/packagecontrol/gridLayout` | [rGridLayoutUpload](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2530) |  |
| DELETE | `/packagecontrol/gridLayout` | [rGridLayoutDelete](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2609) |  |
| GET | `/packagecontrol/key/public/{name}` | [rKeyStoragePublicGet](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L3125) |  |
| GET | `/packagecontrol/key/sample` | [rKeyStorageGetSampleHref](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L3081) |  |
| GET | `/packagecontrol/key/store` | [rKeyStorageGet](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L3099) |  |
| POST | `/packagecontrol/key/store` | [rKeyStorageUpload](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2829) |  |
| PATCH | `/packagecontrol/key/store/{id}` | [rKeyStorageUpdate](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2993) |  |
| DELETE | `/packagecontrol/key/store/{id}` | [rKeyStorageDelete](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L3057) |  |
| POST | `/packagecontrol/package` | [rUploadPackages](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L211) |  |
| GET | `/packagecontrol/package/app` | [rGetPackageApp](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2062) |  |
| GET | `/packagecontrol/package/app/brick` | [rFindPackageAppBrick](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1986) |  |
| POST | `/packagecontrol/package/company` | [rAddPackageCompany](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2127) |  |
| PATCH | `/packagecontrol/package/company` | [rUpdatePackageCompany](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2171) |  |
| DELETE | `/packagecontrol/package/company` | [rDeletePackageCompany](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2234) |  |
| GET | `/packagecontrol/package/count` | [rObtainPackageCount](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L782) |  |
| GET | `/packagecontrol/package/detail` | [rGetPackageDetail](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1851) |  |
| POST | `/packagecontrol/package/detail` | [rAddPackageDetail](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1349) |  |
| PATCH | `/packagecontrol/package/detail` | [rUpdatePackageDetail](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1464) |  |
| GET | `/packagecontrol/package/detail/category` | [rGetPackageDetailCategory](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1927) |  |
| GET | `/packagecontrol/package/detail/count` | [rGetPackageDetailCount](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1899) |  |
| POST | `/packagecontrol/package/detail/export` | [rExportPackageDetail](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2298) |  |
| GET | `/packagecontrol/package/detail/keyword` | [rGetPackageDetailKeyword](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1960) |  |
| GET | `/packagecontrol/package/installable/brick` | [rGetInstallableAppBrick](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L1195) |  |
| GET | `/packagecontrol/package/latest/storageinfo` | [rGetLatestPackageStorageInfos](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L755) |  |
| POST | `/packagecontrol/package/sign` | [rSetPackageSignature](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L3153) |  |
| DELETE | `/packagecontrol/package/sign` | [rDeletePackageSignature](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L3245) |  |
| GET | `/packagecontrol/package/typeValid` | [rValidNewPackageType](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L803) |  |
| GET | `/packagecontrol/packages` | [rGetAllPackageInfos](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L698) |  |
| GET | `/packagecontrol/packages/latest` | [rGetLatestPackageInfos](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L730) |  |
| GET | `/packagecontrol/soln/app/conflict` | [rGetSolutionPackageConflictRequireApp](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L2092) |  |
| GET | `/packagecontrol/stg/{stgId}/version` | [rGetStgPkgVersion](../../WebApp/src/main/java/com/rest/ota/RPackageController.java#L624) |  |

### RStorageManager — `/storagemanager`

原始碼：[RStorageManager.java](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/storagemanager/all/busy/storage` | [RGetStorageBusyCnt](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L201) |  |
| GET | `/storagemanager/byid/busy/storage` | [RCheckStorageBusy](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L192) |  |
| GET | `/storagemanager/byid/storage` | [RGetStorageInfoByID](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L108) |  |
| GET | `/storagemanager/master/storage` | [RGetMasterStorageInfo](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L130) |  |
| POST | `/storagemanager/master/sync` | [RSyncMasterStorage](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L208) |  |
| POST | `/storagemanager/storage` | [RAddStorage](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L42) |  |
| PUT | `/storagemanager/storage` | [RModifyStorage](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L71) |  |
| DELETE | `/storagemanager/storage` | [RDeleteStorage](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L53) |  |
| GET | `/storagemanager/storages` | [RGetAllStorageInfo](../../WebApp/src/main/java/com/rest/ota/RStorageManager.java#L154) |  |

### RUpgradeController — `/upgradecontrol`

原始碼：[RUpgradeController.java](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/upgradecontrol/account/{aid}/installing/count` | [RGetGroupInstallingPkgCountByAccount](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L741) |  |
| GET | `/upgradecontrol/all/upgradestatus` | [RGetAllUpgradeStatus](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L226) |  |
| GET | `/upgradecontrol/bydevice/bypackage/upgradestatus` | [RGetUpgradeStatusByAgentIdPkgName](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L116) |  |
| GET | `/upgradecontrol/bydevice/extantpackage` | [RGetDeviceExtantPkg](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L289) |  |
| DELETE | `/upgradecontrol/bydevice/extantpackage` | [RDelDeviceExtantPackage](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L302) |  |
| GET | `/upgradecontrol/bydevice/install/status` | [RGetDevicePkgInstallStatus](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L570) |  |
| GET | `/upgradecontrol/bydevice/lastfailed/upgradestatus` | [RGetLastfailedUpgradeStatusByAgentId](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L163) |  |
| POST | `/upgradecontrol/bydevice/refresh/status` | [RDevRefreshUpgradeStatus](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L796) |  |
| POST | `/upgradecontrol/bydevice/refresh/sw` | [RDevRefreshSwInfo](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L807) |  |
| GET | `/upgradecontrol/bydevice/summary` | [RGetUpgradeSummaryByDevice](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L818) |  |
| GET | `/upgradecontrol/bydevice/upgradestatus` | [RGetUpgradeStatusByAgentId](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L456) |  |
| GET | `/upgradecontrol/bypkg/install/status` | [RGetPkgInstallStatusByPkgAccount](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L511) |  |
| POST | `/upgradecontrol/deployer` | [RDevPkgDeploy](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L104) |  |
| POST | `/upgradecontrol/devgroup/upgrader` | [RDeviceAndGroupPkgUpgrade](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L397) |  |
| POST | `/upgradecontrol/downloader` | [RDevPkgDownload](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L91) |  |
| POST | `/upgradecontrol/group/{gid}/deployer` | [RGroupPkgDeploy](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L377) |  |
| POST | `/upgradecontrol/group/{gid}/downloader` | [RGroupPkgDownload](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L360) |  |
| GET | `/upgradecontrol/group/{gid}/install/status` | [RGetDevicePkgInstallStatusByGroup](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L543) |  |
| GET | `/upgradecontrol/group/{gid}/installing` | [RGetGroupInstallingPkg](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L592) |  |
| GET | `/upgradecontrol/group/{gid}/installing/count` | [RGetGroupInstallingPkgCount](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L692) |  |
| POST | `/upgradecontrol/group/{gid}/upgrader` | [RGroupPkgUpgrade](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L325) |  |
| GET | `/upgradecontrol/summary` | [RGetUpgradeSummary](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L869) |  |
| GET | `/upgradecontrol/summary/detail` | [RGetUpgradeSummaryDetail](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L920) |  |
| POST | `/upgradecontrol/upgrader` | [RDevPkgUpgrade](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L65) |  |
| DELETE | `/upgradecontrol/upgrader` | [RDevPkgUninstall](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L78) |  |
| GET | `/upgradecontrol/upgrader/norm` | [RGetUpgraderNorm](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L277) |  |
| POST | `/upgradecontrol/upgrader/norm` | [RSetPkgUpgraderNorm](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L269) |  |
| POST | `/upgradecontrol/upgrader/soln` | [RSolutionInstall](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L1021) |  |
| DELETE | `/upgradecontrol/upgrader/soln` | [RSolutionUninstall](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L1034) |  |
| POST | `/upgradecontrol/upgrader/soln/abort` | [RSolutionInstallAbort](../../WebApp/src/main/java/com/rest/ota/RUpgradeController.java#L1058) |  |

### RScheduleController — `/schedulecontrol`

原始碼：[RScheduleController.java](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/schedulecontrol/all/schedule` | [RGetAllSchedule](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L141) |  |
| GET | `/schedulecontrol/all/schedulestatus` | [RGetAllScheduleStatus](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L196) |  |
| GET | `/schedulecontrol/group/{gid}/schedule` | [RGetGroupSchedule](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L266) |  |
| POST | `/schedulecontrol/group/{gid}/schedule` | [RSetGroupSchedule](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L224) |  |
| DELETE | `/schedulecontrol/group/{gid}/schedule` | [RDeleteGroupSchedule](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L249) |  |
| GET | `/schedulecontrol/group/{gid}/schedule/statistics` | [RGetGroupScheduleStatistics](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L300) |  |
| GET | `/schedulecontrol/group/{gid}/somedevice/schedule` | [RGetSomeAgentScheduleByGroupId](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L313) |  |
| POST | `/schedulecontrol/schedule` | [RSetSchedule](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L56) |  |
| DELETE | `/schedulecontrol/schedule` | [RDeleteSchedule](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L84) |  |
| GET | `/schedulecontrol/schedule/cnt` | [RGetScheduleCountByPkgType](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L385) | GetAccount |
| GET | `/schedulecontrol/schedules` | [RGetScheduleByType](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L346) | GetAccount |
| GET | `/schedulecontrol/somedevice/schedule` | [RGetSomeAgentSchedule](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L102) |  |
| GET | `/schedulecontrol/somedevice/schedulestatus` | [RGetSomeAgentScheduleStatus](../../WebApp/src/main/java/com/rest/ota/RScheduleController.java#L158) |  |

### RDeviceManager — `/otadevicemanager`

原始碼：[RDeviceManager.java](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/otadevicemanager/bydevice/softwares` | [rGetSoftwareByAgentId](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L46) |  |
| GET | `/otadevicemanager/group/{gid}/agentIds` | [getGroupDeviceAgentIds](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L160) | EditProcess |
| GET | `/otadevicemanager/group/{gid}/devices` | [getGroupDevice](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L59) | EditProcess |
| GET | `/otadevicemanager/group/{gid}/devices/caninstall` | [rGetInstallableDevice](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L491) | GetDevice |
| GET | `/otadevicemanager/group/{gid}/devices/canuninstall` | [rGetUninstallableDevice](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L576) | GetDevice |
| GET | `/otadevicemanager/group/{gid}/devices/number` | [getGroupDeviceNumber](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L426) | EditProcess |
| GET | `/otadevicemanager/group/{gid}/search/device/byagentid` | [getDevicePagination](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L323) | EditProcess |
| GET | `/otadevicemanager/group/{gid}/search/device/bydevicename` | [searchDevice](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L249) | EditProcess |
| GET | `/otadevicemanager/tagDevice` | [rGetGroupTagDevice](../../WebApp/src/main/java/com/rest/ota/RDeviceManager.java#L220) | EditProcess |

## 容器與邊緣應用

Docker、ROS、異常偵測（ADS）

### DockerMgmt — `/v1/docker`

原始碼：[DockerMgmt.java](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/docker/account/{aid}/busy` | [getAccountDeviceBusyContainers](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L606) | GetAccount, GetDevGroup, GetDocker |
| GET | `/v1/docker/account/{aid}/containers/summary` | [getAccountContainerSummary](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L539) | GetDevGroup, GetDocker |
| GET | `/v1/docker/account/{aid}/containers/summaryBy` | [getAccountContainerByState](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L567) | GetDevGroup, GetDocker |
| GET | `/v1/docker/account/{aid}/devices` | [getAccountHasDockerDevices](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L691) | GetAccount, GetDevGroup, GetDocker |
| POST | `/v1/docker/group/container/create` | [dockerContainerGroupCreate](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1177) | GetDevGroup, GetDocker |
| POST | `/v1/docker/image/option` | [rSetDockerImgOption](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L447) | EditDocker |
| GET | `/v1/docker/registry` | [rGetDockerRegistry](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L299) | GetDocker |
| POST | `/v1/docker/registry` | [rAddDockerRegistry](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L140) | AddDocker |
| PATCH | `/v1/docker/registry` | [rEditDockerRegistry](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L197) | EditDocker |
| DELETE | `/v1/docker/registry` | [rDelDockerRegistry](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L262) | DeleteDocker |
| POST | `/v1/docker/registry/sync` | [rSyncDockerImages](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L349) | EditDocker |
| GET | `/v1/docker/registry/{regId}/image` | [rGetDockerRegistryImage](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L513) | GetDocker |
| GET | `/v1/docker/registry/{regId}/repository` | [rGetDockerRepository](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L490) | GetDocker |
| POST | `/v1/docker/translate/container/create` | [translateDockerCreate](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1912) | GetDocker |
| GET | `/v1/docker/{agentId}/busy` | [getDeviceBusyContainers](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L808) | GetDocker |
| POST | `/v1/docker/{agentId}/container/create` | [dockerContainerCreate](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1050) | AddDocker |
| GET | `/v1/docker/{agentId}/container/{containerId}` | [getDockerContainerInfo](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L900) | GetDocker |
| POST | `/v1/docker/{agentId}/container/{containerId}/kill` | [dockerContainerKill](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1004) |  |
| GET | `/v1/docker/{agentId}/container/{containerId}/logs` | [getDockerContainerLogs](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L918) | GetDocker |
| POST | `/v1/docker/{agentId}/container/{containerId}/pause` | [dockerContainerPause](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1016) |  |
| POST | `/v1/docker/{agentId}/container/{containerId}/remove` | [dockerContainerRemove](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1036) |  |
| POST | `/v1/docker/{agentId}/container/{containerId}/restart` | [dockerContainerRestart](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L992) |  |
| POST | `/v1/docker/{agentId}/container/{containerId}/start` | [dockerContainerStart](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L968) |  |
| GET | `/v1/docker/{agentId}/container/{containerId}/stats` | [getDockerContainerStats](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L947) | GetDocker |
| POST | `/v1/docker/{agentId}/container/{containerId}/stop` | [dockerContainerStop](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L980) |  |
| POST | `/v1/docker/{agentId}/container/{containerId}/unpause` | [dockerContainerUnpause](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1026) |  |
| POST | `/v1/docker/{agentId}/container/{containerId}/update` | [dockerContainerUpdate](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1126) | AddDocker |
| POST | `/v1/docker/{agentId}/containers` | [getDockerContainerList](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L836) | GetDocker |
| GET | `/v1/docker/{agentId}/docker/summary` | [getDockerSummary](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L792) | GetDocker |
| POST | `/v1/docker/{agentId}/image/pull` | [dockerImagePull](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1355) | EditDocker |
| GET | `/v1/docker/{agentId}/image/{imageId}` | [getDockerImageInfo](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1319) | GetDocker |
| DELETE | `/v1/docker/{agentId}/image/{imageId}` | [dockerImageDelete](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1404) | EditDocker |
| GET | `/v1/docker/{agentId}/image/{imageId}/history` | [getDockerImageHistory](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1337) | GetDocker |
| POST | `/v1/docker/{agentId}/images` | [getDockerImageList](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1267) | GetDocker |
| POST | `/v1/docker/{agentId}/images/searchDockerHub` | [searchDockerImageOnDockerHub](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1433) | GetDocker |
| POST | `/v1/docker/{agentId}/network/connect` | [dockerNetworkConnect](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1821) | AddDocker |
| POST | `/v1/docker/{agentId}/network/create` | [dockerNetworkCreate](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1716) | AddDocker |
| POST | `/v1/docker/{agentId}/network/disconnect` | [dockerNetworkDisconnect](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1868) | AddDocker |
| GET | `/v1/docker/{agentId}/network/{networkId}` | [getDockerNetworkInfo](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1692) | GetDocker |
| DELETE | `/v1/docker/{agentId}/network/{networkName}` | [dockerNetworkDelete](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1793) | EditDocker |
| POST | `/v1/docker/{agentId}/networks` | [getDockerNetworkList](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1647) | GetDocker |
| POST | `/v1/docker/{agentId}/volume/create` | [dockerVolumeCreate](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1557) | AddDocker |
| GET | `/v1/docker/{agentId}/volume/{volumeId}` | [getDockerVolumeInfo](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1538) | GetDocker |
| DELETE | `/v1/docker/{agentId}/volume/{volumeName}` | [dockerVolumeDelete](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1614) | EditDocker |
| POST | `/v1/docker/{agentId}/volumes` | [getDockerVolumeList](../../WebApp/src/main/java/com/rest/docker/DockerMgmt.java#L1494) | GetDocker |

### RosMgmt — `/v1/ros`

原始碼：[RosMgmt.java](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| DELETE | `/v1/ros/clear` | [clear](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java#L445) | SetRos |
| POST | `/v1/ros/log-by-level` | [setLogByLevel](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java#L331) | SetRos |
| POST | `/v1/ros/log-by-node` | [setLogByNode](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java#L389) | SetRos |
| GET | `/v1/ros/logs` | [getRosLogs](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java#L131) | GetRos |
| GET | `/v1/ros/logs/history` | [getRosHistoryLogs](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java#L183) | GetRos |
| GET | `/v1/ros/normality` | [getRosNormality](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java#L249) | GetRos |
| POST | `/v1/ros/refresh` | [refresh](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java#L285) | SetRos |
| GET | `/v1/ros/topology/{agentId}` | [getRosTopology](../../WebApp/src/main/java/com/rest/ros/RosMgmt.java#L64) | GetRos |

### ADSMgmt — `/v1/ads`

原始碼：[ADSMgmt.java](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/ads` | [getProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L448) | GetDevice |
| GET | `/v1/ads/anomaly` | [getAnomaly](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L250) | GetScreenShot |
| GET | `/v1/ads/anomaly/group/{groupId}/devices` | [getAnomaly](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L171) | GetScreenShot |
| GET | `/v1/ads/anomaly/last` | [getLastAnomaly](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L347) | GetScreenShot |
| GET | `/v1/ads/anomaly/{anomalyId}` | [getAnomaly](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L410) | GetScreenShot |
| GET | `/v1/ads/device/{agentId}` | [getProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L493) | GetDevice |
| POST | `/v1/ads/device/{agentId}` | [addProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L580) | EditDevice |
| PATCH | `/v1/ads/device/{agentId}` | [updateProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L828) | EditDevice |
| DELETE | `/v1/ads/device/{agentId}` | [deleteProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L976) | EditDevice |
| GET | `/v1/ads/group/{groupId}` | [getProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L533) | GetDevice |
| POST | `/v1/ads/group/{groupId}` | [addProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L653) | EditDevice |
| PATCH | `/v1/ads/group/{groupId}` | [updateProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L897) | EditDevice |
| DELETE | `/v1/ads/group/{groupId}` | [deleteProbe](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L1017) | EditDevice |
| GET | `/v1/ads/setting` | [getSetting](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L139) | GetAdsSetting |
| PATCH | `/v1/ads/setting` | [updateSettings](../../WebApp/src/main/java/com/rest/ads/ADSMgmt.java#L732) | EditAdsSetting |

## 自動化與通知

規則、規則引擎、動作、排程、通知

### RuleMgmt — `/v1/rules`

原始碼：[RuleMgmt.java](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/rules` | [getRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L1696) | GetThreshold |
| POST | `/v1/rules/assignments/groups/options` | [getOptionalAssignedGroupRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L800) | EditDevice |
| POST | `/v1/rules/device` | [addDeviceRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L332) | AddThreshold |
| PUT | `/v1/rules/device` | [editDeviceRule](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L986) | EditThreshold |
| GET | `/v1/rules/devices` | [getDeviceRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L1840) | GetThreshold |
| GET | `/v1/rules/devices/{did}` | [getDeviceRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L1788) | GetThreshold |
| POST | `/v1/rules/group` | [addGroupRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L625) | AddThreshold |
| PUT | `/v1/rules/group` | [editGroupRule](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L1295) | EditThreshold |
| GET | `/v1/rules/groups/options/devices` | [getOptionalGroupRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L2180) | GetThreshold |
| GET | `/v1/rules/groups/options/devices/{did}` | [getOptionalGroupRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L2121) | GetThreshold |
| GET | `/v1/rules/groups/{gid}` | [getGroupRules](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L1892) | GetThreshold |
| GET | `/v1/rules/rulemaps/devices` | [getRuleMap](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L2069) | GetThreshold |
| PUT | `/v1/rules/rulemaps/devices` | [editRuleMap](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L1469) | EditThreshold |
| GET | `/v1/rules/rulemaps/devices/{did}` | [getRuleMap](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L2017) | GetThreshold |
| GET | `/v1/rules/{rid}` | [getRule](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L1943) | GetThreshold |
| DELETE | `/v1/rules/{rid}` | [deleteRule](../../WebApp/src/main/java/com/rest/rule/RuleMgmt.java#L2241) | DeleteThreshold |

### RuleEngineMgmt — `/v1/rule-engines`

原始碼：[RuleEngineMgmt.java](../../WebApp/src/main/java/com/rest/ruleengine/RuleEngineMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/rule-engines` | [getRules](../../WebApp/src/main/java/com/rest/ruleengine/RuleEngineMgmt.java#L71) | GetThreshold |
| POST | `/v1/rule-engines` | [addRuleEngine](../../WebApp/src/main/java/com/rest/ruleengine/RuleEngineMgmt.java#L128) | AddThreshold |
| PUT | `/v1/rule-engines/{ruleId}` | [edieRuleEngine](../../WebApp/src/main/java/com/rest/ruleengine/RuleEngineMgmt.java#L196) | EditThreshold |
| PATCH | `/v1/rule-engines/{ruleId}` | [applyRuleEngine](../../WebApp/src/main/java/com/rest/ruleengine/RuleEngineMgmt.java#L272) | GetThreshold |
| DELETE | `/v1/rule-engines/{ruleId}` | [deleteRuleEngine](../../WebApp/src/main/java/com/rest/ruleengine/RuleEngineMgmt.java#L331) | DeleteThreshold |

### ActionMgmt — `/v1/action`

原始碼：[ActionMgmt.java](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/action/defined` | [getDefined](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L393) |  |
| POST | `/v1/action/defined` | [addDefined](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L836) |  |
| PUT | `/v1/action/defined` | [modifyDefined](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L1162) |  |
| DELETE | `/v1/action/defined/{defined_id}` | [deleteDefined](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L1385) |  |
| GET | `/v1/action/exec` | [getExecs](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L457) |  |
| GET | `/v1/action/exec/check/{defined_id}` | [checkExec](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L537) |  |
| POST | `/v1/action/exec/tally` | [tallyExec](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L1039) |  |
| PUT | `/v1/action/fire/{definedId}` | [fireDefinedAction](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L1077) |  |
| GET | `/v1/action/schedule` | [getSchedule](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L659) |  |
| POST | `/v1/action/schedule` | [addSchedule](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L952) |  |
| PUT | `/v1/action/schedule` | [modifySchedule](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L1293) |  |
| GET | `/v1/action/schedule/{scheduleId}/screenshot/download` | [downloadScreenshots](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L773) |  |
| DELETE | `/v1/action/schedule/{schedule_id}` | [deleteSchedule](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L1439) |  |
| GET | `/v1/action/schedule/{schedule_id}/screenshot` | [getScreenshot](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L746) |  |
| GET | `/v1/action/types` | [getTypes](../../WebApp/src/main/java/com/rest/action/ActionMgmt.java#L305) |  |

### ScheduleMgmt — `/v1/schedules`

原始碼：[ScheduleMgmt.java](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/schedules` | [getSchedules](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java#L1199) | GetPower, GetRecovery |
| POST | `/v1/schedules/devices` | [addDeviceSchs](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java#L197) | EditPower, EditRecovery |
| PUT | `/v1/schedules/devices` | [editDeviceSchs](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java#L1312) | EditPower, EditRecovery |
| POST | `/v1/schedules/groups` | [addGroupsPowerSch](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java#L704) | EditPower, EditRecovery |
| PUT | `/v1/schedules/groups` | [editGroupSchs](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java#L1788) | EditPower, EditRecovery |
| GET | `/v1/schedules/number` | [getScheduleNum](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java#L1252) | GetPower, GetRecovery |
| GET | `/v1/schedules/{sid}` | [getSchedule](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java#L1154) | GetPower, GetRecovery |
| DELETE | `/v1/schedules/{sid}` | [delSchedule](../../WebApp/src/main/java/com/rest/schedule/ScheduleMgmt.java#L2220) | EditPower, EditRecovery |

### NotifyMgmt — `/v1/notifymgmt`

原始碼：[NotifyMgmt.java](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/notifymgmt` | [getAllSetting](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L252) | GetEventNotifySetting |
| GET | `/v1/notifymgmt/bind` | [getEventNotify](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L140) | GetEventNotifySetting |
| POST | `/v1/notifymgmt/bind` | [editMappingTable](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L587) | EditEventNotifySetting |
| DELETE | `/v1/notifymgmt/bind` | [delMappingTable](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L1269) | EditEventNotifySetting |
| GET | `/v1/notifymgmt/category` | [getCategories](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L372) | GetEventNotifySetting |
| POST | `/v1/notifymgmt/custom` | [addCustomEvent](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L489) | EditEventNotifySetting |
| PUT | `/v1/notifymgmt/custom` | [editCustomEvent](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L1166) | EditEventNotifySetting |
| DELETE | `/v1/notifymgmt/custom` | [deleteCustomEvent](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L1329) | EditEventNotifySetting |
| GET | `/v1/notifymgmt/custom/{eid}` | [getCustomEvent](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L447) | GetEventNotifySetting |
| POST | `/v1/notifymgmt/send_email` | [sendEMail](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L681) | GetEmailSetting |
| POST | `/v1/notifymgmt/send_slack` | [sendSlack](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L1075) | GetTeamsSetting |
| POST | `/v1/notifymgmt/send_sms` | [sendSMS_V1](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L771) | GetSMSSetting |
| POST | `/v1/notifymgmt/send_sms_2016` | [sendSMS_V2](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L845) | GetSMSSetting |
| POST | `/v1/notifymgmt/send_teams` | [sendTeams](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L1032) | GetTeamsSetting |
| POST | `/v1/notifymgmt/send_telegram` | [sendTelegram](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L1118) | GetTeamsSetting |
| POST | `/v1/notifymgmt/send_wechat` | [sendWechat](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L920) | GetWechatSetting |
| POST | `/v1/notifymgmt/send_whatsapp` | [sendWhatsApp](../../WebApp/src/main/java/com/rest/notify/NotifyMgmt.java#L982) | GetWhatsAppSetting |

## 系統與整合

系統資訊、設定、授權、Proxy、上下游伺服器路由、IoT Hub、Management Portal、內部 URL

### SystemMgmt — `/v1/system`

原始碼：[SystemMgmt.java](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/system` | [getSystemInfo](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L245) |  |
| POST | `/v1/system` | [updateSettings](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L784) |  |
| POST | `/v1/system/activate` | [getAllSetting](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L802) |  |
| GET | `/v1/system/activate/connectionTest` | [connectionTest](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L301) |  |
| GET | `/v1/system/activation/qrcode` | [getActivationQRCode](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L172) |  |
| GET | `/v1/system/customer` | [getCustomer](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L655) |  |
| POST | `/v1/system/feedback` | [feedback](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L1409) |  |
| GET | `/v1/system/health` | [health](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L165) |  |
| GET | `/v1/system/iscfapp` | [isCFApp](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L233) |  |
| POST | `/v1/system/license/extend` | [extendLicense_V4_5](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L1073) |  |
| GET | `/v1/system/loading` | [getServerLoading](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L316) |  |
| GET | `/v1/system/networks` | [getNetworkCards](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L143) |  |
| GET | `/v1/system/report` | [getSystemReport](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L680) |  |
| GET | `/v1/system/report/{reportId}` | [getSystemReport](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L741) |  |
| GET | `/v1/system/statistics/cpu` | [getStatisticsCPU](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L476) |  |
| GET | `/v1/system/statistics/memory` | [getStatisticsMemory](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L532) |  |
| GET | `/v1/system/statistics/storage` | [getStatisticsStorage](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L590) |  |
| GET | `/v1/system/statistics/uptime` | [getStatisticsUptime](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L430) |  |
| POST | `/v1/system/trialExtend` | [trialExtend_V4_5](../../WebApp/src/main/java/com/rest/system/SystemMgmt.java#L1234) |  |

### SettingMgmt — `/v1/settings`

原始碼：[SettingMgmt.java](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/settings` | [getAllSetting](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L112) | GetEmailSetting, GetLineSetting, GetSMSSetting, GetSlackSetting, GetTeamsSetting, GetTelegramSetting |
| PUT | `/v1/settings` | [setConfig](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L707) | EditEmailSetting, EditLineSetting, EditSMSSetting, EditSlackSetting, EditTeamsSetting, EditTelegramSetting, EditWechatSetting, EditWhatsAppSetting |
| PATCH | `/v1/settings/2fa` | [setEnforce2FA](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1177) |  |
| GET | `/v1/settings/acronis/remote` | [getAcronisRemote](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L299) |  |
| PATCH | `/v1/settings/acronis/remote` | [setAcronisRemote](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1215) |  |
| PATCH | `/v1/settings/criteria` | [setRootOnlyConfig](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L931) |  |
| GET | `/v1/settings/devlog` | [getDeviceSyslog](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L500) | GetDeviceLog |
| PATCH | `/v1/settings/devlog` | [setDeviceSyslog](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1952) | EditDeviceLog |
| GET | `/v1/settings/edgebmc` | [getEdgeBmc](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L629) |  |
| PATCH | `/v1/settings/edgebmc` | [setEdgeBmc](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L2342) |  |
| GET | `/v1/settings/enabled` | [functionalityEnabled](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L257) |  |
| GET | `/v1/settings/filesync` | [getFileSync](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L472) | GetFileSync |
| PATCH | `/v1/settings/filesync` | [setFileSync](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1862) | EditFileSync |
| GET | `/v1/settings/ldap` | [getLdapConfig](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L228) | GetLdapSetting |
| PATCH | `/v1/settings/ldap` | [setLdapConfig](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1076) | EditLdapSetting |
| GET | `/v1/settings/login` | [getLogin](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L571) |  |
| PATCH | `/v1/settings/login` | [setLogin](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L2183) |  |
| GET | `/v1/settings/login/timeout` | [getLoginTimeout](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L603) |  |
| PATCH | `/v1/settings/login/timeout` | [setLoginTimeout](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L2287) |  |
| GET | `/v1/settings/nosql/export` | [getSensorDataExport](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L333) |  |
| PATCH | `/v1/settings/nosql/export` | [setSensorDataExport](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1384) |  |
| GET | `/v1/settings/oamt` | [getOpenAMT](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L442) | GetOpenAMT |
| PATCH | `/v1/settings/oamt` | [setOpenAMT](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1758) | EditOpenAMT |
| GET | `/v1/settings/password/policy` | [getPasswordPolicy](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L659) |  |
| PUT | `/v1/settings/password/policy` | [setPasswordPolicy](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L801) |  |
| GET | `/v1/settings/screenshot` | [getScreenshotConfig](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L198) |  |
| PATCH | `/v1/settings/screenshot` | [setScreenshotConfig](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1033) |  |
| GET | `/v1/settings/syslog` | [getSyslog](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L408) |  |
| PATCH | `/v1/settings/syslog` | [setSyslog](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1618) |  |
| GET | `/v1/settings/system/backup` | [getSystemBackup](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L526) |  |
| PATCH | `/v1/settings/system/backup` | [setSystemBackup](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L2029) |  |
| PATCH | `/v1/settings/system/report` | [setSystemReportConfig](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L990) |  |
| GET | `/v1/settings/webhook` | [getWebhook](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L376) |  |
| PATCH | `/v1/settings/webhook` | [setWebhook](../../WebApp/src/main/java/com/rest/system/SettingMgmt.java#L1512) |  |

### LicenseMgmt — `/v1/license`

原始碼：[LicenseMgmt.java](../../WebApp/src/main/java/com/rest/license/LicenseMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/license` | [getLicenses](../../WebApp/src/main/java/com/rest/license/LicenseMgmt.java#L86) | GetLicense |
| GET | `/v1/license/export` | [exportLicense](../../WebApp/src/main/java/com/rest/license/LicenseMgmt.java#L131) |  |
| POST | `/v1/license/import` | [importLicense](../../WebApp/src/main/java/com/rest/license/LicenseMgmt.java#L180) |  |
| PATCH | `/v1/license/rebind/{serverId}` | [rebindServerId](../../WebApp/src/main/java/com/rest/license/LicenseMgmt.java#L295) |  |

### AppMgmt — `/v1/appinfo`

原始碼：[AppMgmt.java](../../WebApp/src/main/java/com/rest/application/AppMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/appinfo/getEncryptPwd/{pwd}` | [getEncryptPwd](../../WebApp/src/main/java/com/rest/application/AppMgmt.java#L66) |  |
| GET | `/v1/appinfo/info` | [getSRPInfo](../../WebApp/src/main/java/com/rest/application/AppMgmt.java#L145) |  |
| GET | `/v1/appinfo/version` | [getVersion](../../WebApp/src/main/java/com/rest/application/AppMgmt.java#L52) |  |

### ProxyMgmt — `/v1/proxy`

原始碼：[ProxyMgmt.java](../../WebApp/src/main/java/com/rest/proxy/ProxyMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/proxy` | [httpGet](../../WebApp/src/main/java/com/rest/proxy/ProxyMgmt.java#L55) |  |
| POST | `/v1/proxy` | [httpPost](../../WebApp/src/main/java/com/rest/proxy/ProxyMgmt.java#L105) |  |
| PUT | `/v1/proxy` | [httpPut](../../WebApp/src/main/java/com/rest/proxy/ProxyMgmt.java#L201) |  |
| DELETE | `/v1/proxy` | [httpDelete](../../WebApp/src/main/java/com/rest/proxy/ProxyMgmt.java#L264) |  |
| POST | `/v1/proxy/node-red` | [proxyNodeRED](../../WebApp/src/main/java/com/rest/proxy/ProxyMgmt.java#L177) |  |

### RouteMgmt — `/v1/route`

原始碼：[RouteMgmt.java](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/route/auth-code` | [getAuthCode](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java#L154) | GetRouteToken |
| POST | `/v1/route/auth-code` | [importAuthCode](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java#L187) | AddRouteToken |
| GET | `/v1/route/downstream` | [getDownstreamServers](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java#L115) |  |
| POST | `/v1/route/downstream` | [addDownstreamServer](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java#L262) | AddServerRoute |
| PATCH | `/v1/route/downstream` | [editDownstreamServer](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java#L392) | EditServerRoute |
| DELETE | `/v1/route/downstream` | [removeDownstreamServer](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java#L483) | DeleteServerRoute |
| GET | `/v1/route/upstream` | [getUpstreamServer](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java#L95) |  |
| PATCH | `/v1/route/upstream` | [enableUpstreamServer](../../WebApp/src/main/java/com/rest/route/RouteMgmt.java#L331) | EditServerRoute |

### ServiceMgmt — `/v1/iothub`

原始碼：[ServiceMgmt.java](../../WebApp/src/main/java/com/rest/service/ServiceMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/iothub/credential` | [getProtocols](../../WebApp/src/main/java/com/rest/service/ServiceMgmt.java#L191) |  |
| GET | `/v1/iothub/credential/standalone` | [getProtocols](../../WebApp/src/main/java/com/rest/service/ServiceMgmt.java#L147) |  |
| GET | `/v1/iothub/credential/{IOTKEY}` | [getIoTCredential](../../WebApp/src/main/java/com/rest/service/ServiceMgmt.java#L65) |  |
| POST | `/v1/iothub/remote_provisioning` | [provisioning](../../WebApp/src/main/java/com/rest/service/ServiceMgmt.java#L249) | RemoteProvisioning |

### MPMgmt — `/v1/mp`

原始碼：[MPMgmt.java](../../WebApp/src/main/java/com/rest/managementportal/MPMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/mp/remote_url` | [getHostUrl](../../WebApp/src/main/java/com/rest/managementportal/MPMgmt.java#L309) |  |
| POST | `/v1/mp/service_keys` | [postKey](../../WebApp/src/main/java/com/rest/managementportal/MPMgmt.java#L325) | AddServiceKey |
| PUT | `/v1/mp/service_keys/{service_key_guid}` | [refreshKey](../../WebApp/src/main/java/com/rest/managementportal/MPMgmt.java#L591) | AddServiceKey, DeleteServiceKey |
| DELETE | `/v1/mp/service_keys/{service_key_guid}` | [delKey](../../WebApp/src/main/java/com/rest/managementportal/MPMgmt.java#L735) | DeleteServiceKey |
| PUT | `/v1/mp/service_keys/{service_key_guid}/operations/disable_service_key` | [disableKey](../../WebApp/src/main/java/com/rest/managementportal/MPMgmt.java#L401) | EditServiceKey |
| PUT | `/v1/mp/service_keys/{service_key_guid}/operations/enable_service_key` | [enableKey](../../WebApp/src/main/java/com/rest/managementportal/MPMgmt.java#L496) | EditServiceKey |

### InternalMgmt — `/v1/internal`

原始碼：[InternalMgmt.java](../../WebApp/src/main/java/com/rest/internal/InternalMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/internal/urls` | [getURLs](../../WebApp/src/main/java/com/rest/internal/InternalMgmt.java#L37) |  |

## 前端設定

Dashboard、版面、UI 與 plugin 設定

### DashboardMgmt — `/v1/dashboard`

原始碼：[DashboardMgmt.java](../../WebApp/src/main/java/com/rest/dashboard/v1/DashboardMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| POST | `/v1/dashboard/sheet` | [createSheet](../../WebApp/src/main/java/com/rest/dashboard/v1/DashboardMgmt.java#L131) | AddDashboard |
| PUT | `/v1/dashboard/sheet` | [updateSheet](../../WebApp/src/main/java/com/rest/dashboard/v1/DashboardMgmt.java#L269) | EditDashboard |
| GET | `/v1/dashboard/sheets/accounts/{aid}` | [getSheet](../../WebApp/src/main/java/com/rest/dashboard/v1/DashboardMgmt.java#L64) | GetDashboard |
| DELETE | `/v1/dashboard/sheets/{did}` | [deleteSheet](../../WebApp/src/main/java/com/rest/dashboard/v1/DashboardMgmt.java#L418) | DeleteDashboard |

### LayoutMgmt — `/v1/layout`

原始碼：[LayoutMgmt.java](../../WebApp/src/main/java/com/rest/layout/LayoutMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/layout` | [getLayout](../../WebApp/src/main/java/com/rest/layout/LayoutMgmt.java#L39) |  |
| PUT | `/v1/layout` | [saveLayout](../../WebApp/src/main/java/com/rest/layout/LayoutMgmt.java#L74) |  |

### UiConfigMgmt — `/v1/ui-config`

原始碼：[UiConfigMgmt.java](../../WebApp/src/main/java/com/rest/frontend/UiConfigMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/ui-config/my` | [getUserConfig](../../WebApp/src/main/java/com/rest/frontend/UiConfigMgmt.java#L40) |  |
| POST | `/v1/ui-config/my` | [saveUserConfig](../../WebApp/src/main/java/com/rest/frontend/UiConfigMgmt.java#L83) |  |
| DELETE | `/v1/ui-config/my` | [deleteUserConfig](../../WebApp/src/main/java/com/rest/frontend/UiConfigMgmt.java#L144) |  |
| GET | `/v1/ui-config/system` | [getSystemConfig](../../WebApp/src/main/java/com/rest/frontend/UiConfigMgmt.java#L66) |  |
| POST | `/v1/ui-config/system` | [saveSystemConfig](../../WebApp/src/main/java/com/rest/frontend/UiConfigMgmt.java#L110) |  |
| DELETE | `/v1/ui-config/system` | [deleteSystemConfig](../../WebApp/src/main/java/com/rest/frontend/UiConfigMgmt.java#L166) |  |

### PluginConfigMgmt — `/v1/plugin-config`

原始碼：[PluginConfigMgmt.java](../../WebApp/src/main/java/com/rest/frontend/PluginConfigMgmt.java)

| Method | 路徑 | Java 方法 | 權限 |
|---|---|---|---|
| GET | `/v1/plugin-config/{pluginName}` | [getPluginConfig](../../WebApp/src/main/java/com/rest/frontend/PluginConfigMgmt.java#L49) |  |
| PUT | `/v1/plugin-config/{pluginName}` | [savePluginConfig](../../WebApp/src/main/java/com/rest/frontend/PluginConfigMgmt.java#L134) |  |
| PATCH | `/v1/plugin-config/{pluginName}` | [editPluginConfig](../../WebApp/src/main/java/com/rest/frontend/PluginConfigMgmt.java#L229) |  |
| DELETE | `/v1/plugin-config/{pluginName}` | [deletePluginConfig](../../WebApp/src/main/java/com/rest/frontend/PluginConfigMgmt.java#L267) |  |
| GET | `/v1/plugin-config/{pluginName}/{configName}` | [getPluginConfig](../../WebApp/src/main/java/com/rest/frontend/PluginConfigMgmt.java#L88) |  |
| PUT | `/v1/plugin-config/{pluginName}/{configName}` | [editPluginConfig](../../WebApp/src/main/java/com/rest/frontend/PluginConfigMgmt.java#L176) |  |
| DELETE | `/v1/plugin-config/{pluginName}/{configName}` | [deletePluginConfig](../../WebApp/src/main/java/com/rest/frontend/PluginConfigMgmt.java#L302) |  |

## WebSocket

以 `@ServerEndpoint` 宣告，路徑直接接在主機後面（例如 `wss://<host>/terminal/...`），**沒有 `/rmm`**。

| 路徑 | 類別 | 用途 |
|---|---|---|
| `/terminal/{authinfo}/{agentId}/{sessionId}` | [Terminal](../../WebApp/src/main/java/com/websocket/terminal/Terminal.java) | 遠端終端機 |
| `/wsdata/{authorization}` | [WSData](../../WebApp/src/main/java/com/websocket/wsdata/WSData.java) | 即時資料推送 |
| `/feeder/{authorization}` | [Feeder](../../WebApp/src/main/java/com/websocket/wsdata/Feeder.java) | 資料 feeder |
| `/event/{lang}/{authinfo}` | [Event](../../WebApp/src/main/java/com/websocket/event/Event.java) | 事件推送 |
| `/signaling/{roomId}` | [Signaling](../../WebApp/src/main/java/com/websocket/signaling/Signaling.java) | WebRTC signaling（KVM 檔案傳輸等） |
| `/edgebmc/{clientType}/{bmcAgentId}/{path}` | [EdgeBmc](../../WebApp/src/main/java/com/websocket/edgebmc/EdgeBmc.java) | EdgeBMC 轉送 |
| `/webrelay.ashx` | [iamt.Server](../../WebApp/src/main/java/com/websocket/iamt/Server.java) | Intel AMT web relay |
