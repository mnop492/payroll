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

## 4. 品牌側欄 (Brand Sidebar) — 多品牌/多分站情境

當系統需要同時管理多個品牌或分公司時，增加一層品牌切換側欄：

視覺特點： 白色卡片風格，位於主內容區左側、與主側欄垂直並列；每個品牌以獨立卡片呈現，包含品牌名稱與代碼。

功能配置：
- 上方標題列與搜尋框，支援快速過濾品牌列表
- 預設僅顯示頂部 N 個品牌，超出部分以「顯示更多」按鈕展開
- 作用中品牌以深色反白（`bg-gray-900 text-white`）標示

計薪應用： 切換品牌時，不重新整理整個頁面，僅更新所屬員工、考勤、佣金設定與薪資結算結果。

斷點行為： 在窄螢幕（< 1024px）可考慮隱藏品牌側欄，改為下拉選單或 Modal 選取。

---

## 5. 響應式斷點策略 (Responsive Breakpoints)

建議 Tailwind 預設斷點為基礎，針對後台場景微調：

| 斷點 | 寬度 | Sidebar | Brand Sidebar | 表格 |
|------|------|---------|---------------|------|
| `sm` | ≥ 640px | 維持展開 | 隱藏（改下拉） | 水平捲動 |
| `md` | ≥ 768px | 維持展開 | 隱藏（改下拉） | 水平捲動 |
| `lg` | ≥ 1024px | 維持展開 | 可選展開/收起 | 正常顯示 |
| `xl` | ≥ 1280px | 維持展開 | 展開 | 正常顯示 |

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

## 7. 互動元件統一風格 (UI Components)

| 元件 | Tailwind 樣式規範 |
|------|------------------|
| **按鈕 (Button)** | `rounded-xl px-4 py-2 text-sm font-bold transition-colors` |
| **主要按鈕** | `bg-blue-600 text-white hover:bg-blue-700` |
| **次要按鈕** | `border border-gray-300 text-gray-600 hover:bg-gray-50` |
| **危險按鈕** | `bg-red-600 text-white hover:bg-red-700` |
| **成功按鈕** | `bg-green-600 text-white hover:bg-green-700` |
| **卡片 (Card)** | `bg-white rounded-2xl shadow-sm border border-gray-200 overflow-hidden` |
| **表格標題** | `bg-gray-100 text-center text-xs font-semibold text-gray-600 uppercase tracking-wider` |
| **表格行** | `border-b border-gray-100 hover:bg-gray-50 odd:bg-white even:bg-gray-50/50 transition-colors` |
| **標籤 (Badge)** | `inline-block text-xs px-2.5 py-0.5 rounded-full font-semibold` |
| **輸入框** | `px-3 py-2.5 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none` |
| **Modal** | `fixed inset-0 z-50 items-center justify-center hidden modal` + `bg-black/40` 遮罩 |
| **Toast / Flash** | `flex items-center justify-between px-4 py-3 rounded-xl border` + 顏色映射 |

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