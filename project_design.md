🛠️ 企業級後台的「三大黃金結構」
不論你最終選擇用 React 還是純 HTML 搭配 Tailwind CSS，你都可以直接命令 DeepSeek 按照以下結構幫你切版（Layout）：

1. 左側固定導航欄 (Sidebar Navigation)
視覺特點： 通常採用深色系（如深藍、深灰）或極簡的純白。

功能配置： 頂部放置公司或系統標誌（Logo），下方則是一列帶有小圖示（Icons）的選單（例如：首頁看板、員工管理、出勤記錄、薪資結算、系統設定）。

計薪應用： 點擊不同的選單，右側的主畫面會流暢地切換，不需要重新整理整個網頁。

2. 頂部狀態列 (Top Header)
視覺特點： 橫向窄條，通常保持純白底色，帶有一條淡淡的下邊框（Border）。

功能配置： 左側顯示當前所在的頁面名稱（如：首頁看板 / 2026年7月份薪資核算），右側放置搜尋框、通知鈴鐺以及管理員的頭像與名稱。

3. 中央數據大看板 (Main Dashboard Grid)
這是整個網頁的核心，通常會使用 Grid（網格） 或 Flexbox 佈局，由上至下分成三個區塊：

頂層：數據指標卡片 (Metric Cards)

一排 3 到 4 個小卡片。每個卡片內包含一個醒目的粗體數字和一個小標題。

計薪系統範例：「本月應發總薪資：$245,000」、「已確認打卡人數：128人」、「待審批加班申請：5件」。

中層：圖表與趨勢 (Charts & Analytics)

佔據較大面積的卡片，內嵌折線圖（Line Chart）或長條圖（Bar Chart）。

計薪系統範例： 用折線圖展示「近半年公司人力成本走勢」，或用圓環圖展示「員工部門薪資佔比」。

底層：精細數據表格 (Data Tables)

採用斑馬紋（Zebra Stripes）或白底細線的表格，具備清晰的欄位標題、狀態標籤（如：綠色代表「已發放」、黃色代表「審核中」）以及右側的「操作」按鈕。

---

## 4. 品牌切換器 (Brand Switcher) — 多品牌/多分站情境

當系統需要同時管理多個品牌或分公司時，在頂部狀態列加入精緻的下拉選單，取代獨立的品牌側欄。

視覺特點： 位於頂部標題旁，一個輕量的圓角按鈕，展開後為附有搜尋框的下拉面板。

功能配置：
- 按鈕顯示當前品牌名稱，右側帶有 `▼` 圖示
- 點擊展開下拉面板，內含搜尋框與品牌列表
- 輸入文字可即時過濾品牌名稱與代碼
- 點擊品牌選項立即導向該品牌的對應頁面
- 作用中品牌以淺藍色背景（`bg-blue-50 text-blue-700`）標示

計薪應用： 切換品牌時，重新導向當前頁面並帶上 `?brand=<code>` 參數，所有數據自動更新。

斷點行為： 下拉選單在所有螢幕尺寸皆可用，無需額外斷點處理。

| 斷點 | 寬度 | Sidebar | Brand Switcher | 表格 |
|------|------|---------|---------------|------|
| `sm` | ≥ 640px | 維持展開 | 下拉選單 | 水平捲動 |
| `md` | ≥ 768px | 維持展開 | 下拉選單 | 水平捲動 |
| `lg` | ≥ 1024px | 維持展開 | 下拉選單 | 正常顯示 |
| `xl` | ≥ 1280px | 維持展開 | 下拉選單 | 正常顯示 |

手機端（< 640px）可將側欄改為 overlay draw（`fixed inset-0 z-50` 覆蓋層）。

---

## 6. 狀態容器規範 (Loading / Empty / Error)

每個數據區塊應涵蓋三種狀態：

- **Loading**：資料載入中，顯示骨架屏（Skeleton）或旋轉動畫（`animate-spin`），避免 layout shift
- **Empty**：無資料時顯示友善插圖與提示文字，如「尚無考勤數據，請先匯入 Excel」
- **Error**：API 錯誤時顯示警示卡片與重試按鈕

計薪應用範例：
```
考勤表格 Empty: 📭 尚無任何考勤數據，請先匯入或手動新增本月資料
Chart Empty: 📊 本月無時薪制員工資料，無法產生圖表
```

---

## 7. 互動元件統一風格 (UI Components) — 企業級 SaaS 標準 (v2)

### 基礎色系
- **背景**：主內容區 `bg-slate-50`
- **卡片**：`bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6`（無彩色邊框）
- **文字主色**：`text-slate-800`（標題）、`text-slate-500`（次要）、`text-slate-700`（內文）

### 卡片內部標題與操作區
```html
<div class="flex justify-between items-center mb-5">
  <h3 class="text-lg font-semibold text-slate-800">📋 標題文字</h3>
  <button class="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium py-2 px-4 rounded-lg transition-colors shadow-sm">動作按鈕</button>
</div>
```

### 按鈕 (Button)
| 類型 | Tailwind 類別 |
|------|--------------|
| **主要按鈕** | `bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium py-2 px-4 rounded-lg transition-colors shadow-sm` |
| **次要按鈕** | `border border-slate-300 text-slate-600 hover:bg-slate-50 text-sm font-medium py-2 px-4 rounded-lg transition-colors` |
| **危險按鈕** | `bg-red-600 hover:bg-red-700 text-white text-sm font-medium py-2 px-4 rounded-lg transition-colors shadow-sm` |
| **危險邊框** | `border border-red-300 text-red-600 hover:bg-red-50 text-sm font-medium py-2 px-4 rounded-lg transition-colors` |

### 數據表格 (Data Tables)
```html
<table class="w-full text-left border-collapse">
  <thead>
    <tr class="bg-slate-50 border-y border-slate-200">
      <th class="text-xs font-semibold text-slate-500 uppercase tracking-wider py-3 px-4">欄位</th>
    </tr>
  </thead>
  <tbody>
    <tr class="border-b border-slate-100 hover:bg-slate-50 transition-colors">
      <td class="py-3 px-4 text-sm text-slate-700">內容</td>
    </tr>
  </tbody>
</table>
```

### 狀態標籤 (Pill Badges)
```html
<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium">
```
| 情境 | 顏色 |
|------|------|
| 嚴重錯誤/缺資料 | `bg-red-100 text-red-800` |
| 警告/未錄入 | `bg-amber-100 text-amber-800` |
| 正常/時薪制 | `bg-blue-100 text-blue-800` |
| 一般資訊/月薪制 | `bg-purple-100 text-purple-800` |
| 成功/一致 | `bg-green-100 text-green-800` |

### 頁籤切換 (Tabs) — Segmented Control 樣式
採用底部底線或分段控制器，避免氣泡框風格：
```html
<div class="flex border-b border-slate-200 gap-0" role="tablist">
  <button class="px-4 py-2.5 text-sm font-medium text-slate-700 border-b-2 border-transparent hover:text-slate-900 hover:border-slate-300 transition-colors" data-tab="hourly" role="tab">時薪制</button>
  <button class="px-4 py-2.5 text-sm font-medium text-slate-700 border-b-2 border-blue-600 text-blue-600" data-tab="monthly" role="tab">月薪制</button>
</div>
```

### 卡片 (Card)
`bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6`
（**禁止**使用彩色邊框如 `border-blue-200`、`border-amber-200`、`border-green-200`）

### 舊版 (v1) 元件速查 — 保留向後相容
| 元件 | 舊樣式 | 新樣式 (v2) |
|------|--------|------------|
| 卡片外框 | `rounded-2xl border-gray-200` | `rounded-xl border-slate-200` |
| 表格標題背景 | `bg-gray-100` | `bg-slate-50 border-y border-slate-200` |
| 表格標題文字 | `text-gray-600` | `text-slate-500` |
| 表格儲存格 | `px-3 py-2.5` | `py-3 px-4` |
| Badge 基礎 | `inline-block rounded-full` | `inline-flex items-center rounded-full` |
| 輸入框邊框 | `border-gray-300` | `border-slate-300` |

---

## 8. 多品牌 API 設計要點

- 所有路由接受 `?brand=<brand_code>` 查詢參數
- 未指定品牌時使用 `DEFAULT_BRAND_CODE` 回退
- 品牌切換純前端：點擊品牌卡片 → `URLSearchParams.set('brand', code)` → 重新導向
- 檔案上傳時自動偵測品牌（透過 `getBrandKeywords()` 比對檔名關鍵字）
- 權限控制：使用者只能看到被授權的品牌列表

---

## 9. 即時反饋與 UX 細節

- **表單操作**：點擊按鈕後應即時 disabled 並顯示文字（如「儲存中…」）防止重複提交
- **刪除確認**：使用 `confirm('確定刪除？')` 或自訂 Modal
- **快速操作列**：在長頁面底部提供 sticky 操作列，讓使用者不必滾回頂部即可重新結算
- **空白狀態**：所有表格應有 `{% else %}` 分支顯示友善提示，而非空白表格
- **鍵盤無障礙**：`role="tablist"`、`aria-label`、`tabindex` 等屬性確保可用 Tab 導航