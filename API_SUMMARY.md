# API 參考文件 — 數據管理系統

> **Base URL:** `http://<host>:5000`
> **Auth:** 所有 `/api/*` 需帶 API Key（設於 `config.ini [API] api_key`）

---

## 快速入門

```bash
# 方式一：Header（建議）
curl -H "X-API-Key: my-secret-api-key-123" http://localhost:5000/api/v1/run_query

# 方式二：Query 參數（較不安全）
curl "http://localhost:5000/api/v1/report/sale?api_key=my-secret-api-key-123"
```

---

## 端點一覽

| # | 方法 | 路由 | 說明 |
|---|------|------|------|
| 1 | **POST** | `/api/v1/run_query` | 同步所有遠端銷售/出勤/產品資料 |
| 2 | **GET** | `/api/v1/report/{type}` | 讀取本機報表 Excel（JSON 陣列） |
| 3 | **POST** | `/api/v1/add_to_action/{type}` | 新增待處理項目至 Excel |
| 4 | **POST** | `/api/v1/delete_from_action/{type}` | 從 Excel 刪除特定項目 |
| 5 | **POST** | `/api/v1/clear_action/{type}` | 清空 Excel（保留欄位） |
| 6 | **POST** | `/api/v1/execute_action/{type}` | 執行操作（寫入遠端 API） |
| 7 | **GET** | `/api/v1/config` | 讀取系統設定 (`config.ini`) |
| 8 | **POST** | `/api/v1/config` | 儲存系統設定 |
| 9 | **GET** | `/api/v1/log/{type}` | 讀取歷史執行日誌 |
| 10 | **GET** | `/api/v1/console` | 讀取系統終端機輸出 |
| 11 | **POST** | `/api/v1/console/clear` | 清空終端機記錄 |

---

## 詳細規格

### 1. 同步遠端資料

```http
POST /api/v1/run_query
Content-Type: application/json
X-API-Key: {api_key}
```

```
Request:  無 Body
Response: {"status":"success","message":"遠端數據同步完成！"}
```

---

### 2. 讀取報表資料

```http
GET /api/v1/report/{report_type}
X-API-Key: {api_key}
```

| `report_type` | 對應 Excel 檔案 |
|--------------|----------------|
| `sale` | `Data/All_USER_SALEREPORT.xlsx` |
| `profile` | `Data/All_USER_PROFILE.xlsx` |
| `product` | `Data/All_USER_PRODUCT.xlsx` |
| `duty` | `Data/All_USER_DUTY.xlsx` |
| `insert` | `Data/All_USER_INSERT.xlsx` |
| `cancel` | `Data/All_USER_CANCEL.xlsx` |
| `push` | `Data/All_USER_PUSH.xlsx` |

```
Response: [
  {"account":"user01","headerID":"12345","productName":"冷氣", ...},
  {"account":"user01","headerID":"12346","productName":"冰箱", ...}
]
```
> ⚠️ 檔案不存在或讀取失敗時回傳空陣列 `[]`。

---

### 3. 新增待處理項目

```http
POST /api/v1/add_to_action/{action_type}
Content-Type: application/json
X-API-Key: {api_key}
```

```json
// Request Body
[
  {"account": "user01", "headerID": "12345", "productName": "冷氣", ...},
  {"account": "user02", "headerID": "12346", ...}
]

// Response
{"status":"success","message":"成功加入 2 筆紀錄！"}
```

> 💡 會自動依 `(account, headerID)` 去重，重複的以最後一筆為準。

---

### 4. 刪除待處理項目

```http
POST /api/v1/delete_from_action/{action_type}
Content-Type: application/json
X-API-Key: {api_key}
```

```json
// Request Body
[
  {"account": "user01", "headerID": "12345"},
  {"account": "user02", "headerID": "12346"}
]

// Response
{"status":"success","message":"刪除成功！"}
```

---

### 5. 清空待處理項目

```http
POST /api/v1/clear_action/{action_type}
Content-Type: application/json
X-API-Key: {api_key}
```

```json
// Response
{"status":"success","message":"檔案已清空！"}
```

---

### 6. 執行操作（寫入遠端 API） 🔥

```http
POST /api/v1/execute_action/{action_type}
Content-Type: application/json
X-API-Key: {api_key}
```

| `action_type` | 行為 | 遠端 API |
|--------------|------|---------|
| `insert` | 新增銷售記錄 | `salesReportHeader/insert` |
| `cancel` | 取消銷售記錄 | `salesReportHeader/cancel` |
| `push` | 先取消舊單 + 新增新單（更新） | 兩者皆執行 |

**模式 A — 執行全部**

```json
// Request
{"mode": "all"}

// Response
{"status":"success","message":"✅ 已成功執行 INSERT 操作，並已備份至 log 資料夾！"}
```

**模式 B — 只執行選取**

```json
// Request
{
  "mode": "selected",
  "data": [
    {"account": "user01", "headerID": "12345", "productName": "冷氣", ...},
    {"account": "user01", "headerID": "12346", ...}
  ]
}

// Response
{"status":"success","message":"✅ 已成功執行 INSERT 操作，並已備份至 log 資料夾！"}
```

> ⚡ 執行成功後自動從 Excel 剔除已處理項目，並備份到 `log/` 資料夾。

---

### 7. 讀取系統設定

```http
GET /api/v1/config
X-API-Key: {api_key}
```

```json
// Response
{
  "status": "success",
  "data": {
    "LOGIN": {"logininfo": "user01,pass123\nuser02,pass456"},
    "INFO": {"appkey": "1c38dedb", "appname": "LetsLink", ...},
    "SALEREPORT": {"size": "800", "startdate": "2025-11-01", "enddate": "2025-11-30"},
    "PROXY": {"enableproxy": "", "server": "127.0.0.1", "port": "8888"},
    "DUTYREPORT": {"month": "2025-11"},
    "API": {"api_key": "my-secret-api-key-123", "cors_enabled": "true"},
    "RATE_LIMIT": {"insert_min_delay": "3.0", "insert_max_delay": "7.0", ...}
  }
}
```

---

### 8. 儲存系統設定

```http
POST /api/v1/config
Content-Type: application/json
X-API-Key: {api_key}
```

Body 格式需與 GET 回傳的 `data` 結構相同：

```json
// Request — 只傳要修改的部分即可
{
  "SALEREPORT": {"startdate": "2025-12-01", "enddate": "2025-12-31"},
  "RATE_LIMIT": {"insert_max_delay": "5.0"}
}

// Response
{"status":"success","message":"✅ 系統設定已成功儲存，且記憶體已同步更新！"}
```

> 💡 儲存後會自動重新載入 `media` 模組，新設定立即生效。

---

### 9. 歷史日誌

```http
GET /api/v1/log/{log_type}
X-API-Key: {api_key}
```

| `log_type` | 對應日誌檔 |
|-----------|-----------|
| `insert` | `log/All_USER_INSERT.xlsx` |
| `cancel` | `log/All_USER_CANCEL.xlsx` |
| `push` | `log/All_USER_PUSH.xlsx` |

```json
// Response — 按 ExecuteTime 降冪排序
[
  {"account":"user01","headerID":"12345","ExecuteTime":"2025-11-15 14:30:22", ...},
  {"account":"user02","headerID":"12346","ExecuteTime":"2025-11-15 14:28:10", ...}
]
```

---

### 10. 終端機

```http
GET  /api/v1/console        # 讀取（最後 1000 行）
POST /api/v1/console/clear  # 清空
```

```json
// GET Response
{"log": "user01 login successfully!\nuser01 has no record from ...\n"}

// POST Response
{"status":"success","message":"終端機紀錄已清空"}
```

---

## 常見 HTTP 狀態碼

| 狀態碼 | 含義 | 回應範例 |
|--------|------|---------|
| **200** | 成功 | `{"status":"success","message":"..."}` |
| **400** | 參數錯誤 | `{"status":"error","message":"無效參數"}` |
| **401** | 未授權 | `{"status":"error","message":"unauthorized: 缺少或無效的 API Key"}` |
| **500** | 伺服器錯誤 | `{"status":"error","message":"執行失敗: ..."}` |

---

## Python 呼叫範例

```python
import requests

API_BASE = "http://localhost:5000/api/v1"
HEADERS = {"X-API-Key": "my-secret-api-key-123"}

# 1. 同步資料
requests.post(f"{API_BASE}/run_query", headers=HEADERS)

# 2. 讀取銷售報表
resp = requests.get(f"{API_BASE}/report/sale", headers=HEADERS)
data = resp.json()  # list of dicts

# 3. 新增待取消項目
requests.post(
    f"{API_BASE}/add_to_action/cancel",
    headers={**HEADERS, "Content-Type": "application/json"},
    json=[{"account": "user01", "headerID": "12345"}]
)

# 4. 執行取消
requests.post(
    f"{API_BASE}/execute_action/cancel",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={"mode": "all"}
)
```

---

## JavaScript / fetch 範例

```javascript
const API = "http://localhost:5000/api/v1";
const HEADERS = { "X-API-Key": "my-secret-api-key-123" };

// 讀取報表
fetch(`${API}/report/sale`, { headers: HEADERS })
  .then(r => r.json())
  .then(data => console.log(data));

// 執行 Insert
fetch(`${API}/execute_action/insert`, {
  method: "POST",
  headers: { ...HEADERS, "Content-Type": "application/json" },
  body: JSON.stringify({ mode: "all" })
});
```

---

## cURL 速查

```bash
# 同步
curl -X POST -H "X-API-Key: my-secret-api-key-123" http://localhost:5000/api/v1/run_query

# 讀取
curl "http://localhost:5000/api/v1/report/sale?api_key=my-secret-api-key-123"

# 新增
curl -X POST -H "X-API-Key: my-secret-api-key-123" \
  -H "Content-Type: application/json" \
  -d '[{"account":"user01","headerID":"12345"}]' \
  http://localhost:5000/api/v1/add_to_action/cancel

# 執行全部
curl -X POST -H "X-API-Key: my-secret-api-key-123" \
  -H "Content-Type: application/json" \
  -d '{"mode":"all"}' \
  http://localhost:5000/api/v1/execute_action/insert
```
