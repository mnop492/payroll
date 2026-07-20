// ── DOM 快取 ──
const domCache = {
    attModalPromoter: null,
    attModalLoc: null,
    dailyRecordsBody: null,
    attendanceCalendarGrid: null,
    attendanceCalendarContent: null,
    attendanceCalendarToggle: null,
    init() {
        this.attModalPromoter = document.getElementById('att_modal_promoter');
        this.attModalLoc = document.getElementById('att_modal_loc');
        this.dailyRecordsBody = document.getElementById('daily_records_body');
        this.attendanceCalendarGrid = document.getElementById('attendance_calendar_grid');
        this.attendanceCalendarContent = document.getElementById('attendanceCalendarContent');
        this.attendanceCalendarToggle = document.getElementById('attendanceCalendarToggle');
    }
};

// ── 防抖工具 ──
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

let handleAttModalChangeDebounced = null;
let handleSalesModalChangeDebounced = null;

// 初始化 DOM 快取和防抖
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        domCache.init();
        handleAttModalChangeDebounced = debounce(handleAttModalChangeImpl, 150);
        handleSalesModalChangeDebounced = debounce(handleSalesModalChangeImpl, 150);
    });
} else {
    domCache.init();
    handleAttModalChangeDebounced = debounce(handleAttModalChangeImpl, 150);
    handleSalesModalChangeDebounced = debounce(handleSalesModalChangeImpl, 150);
}

const pageDataElement = document.getElementById('index-page-data');
const pageData = pageDataElement ? JSON.parse(pageDataElement.textContent) : {};
const currentMonth = pageData.currentMonth || '';

// ── 暫存陣列：批次寫入用 ──
let pendingAttendanceRows = [];
let pendingSalesRows = [];

// ── 智慧地點排序工具 ──
function getLocMap(id) {
    try { return JSON.parse(document.getElementById(id)?.textContent || '{}'); } 
    catch(e) { return {}; }
}

function reorderLocationDropdown(selectId, activeLocs) {
    const sel = document.getElementById(selectId);
    if (!sel) return;

    const currentVal = sel.value; // 記住當前選擇
    const options = Array.from(sel.options).slice(1); // 排除第一個 "-- 選擇地點 --"

    const activeOptions = [];
    const inactiveOptions = [];

    options.forEach(opt => {
        // 先還原最純淨的文字與樣式
        let pureVal = opt.value;
        opt.text = pureVal;
        
        if (activeLocs.includes(pureVal)) {
            opt.text = '⭐ ' + pureVal;
            opt.style.backgroundColor = '#1e293b'; // 深色背景 (slate-800)
            opt.style.color = '#fbbf24';           // 琥珀亮黃字體 (amber-400)
            opt.style.fontWeight = 'bold';
            activeOptions.push(opt);
        } else {
            opt.style.backgroundColor = '';
            opt.style.color = '';
            opt.style.fontWeight = '';
            inactiveOptions.push(opt);
        }
    });

    // 清空並依序塞回：Placeholder -> 活躍地點 -> 其他地點
    sel.options.length = 1;
    activeOptions.forEach(opt => sel.add(opt));
    inactiveOptions.forEach(opt => sel.add(opt));

    sel.value = currentVal; // 恢復選擇
}
let currentAttendanceRecords = [];
let selectedAttendanceDates = new Set();
let isAttendanceCalendarCollapsed = true;

function toggleAttendanceCalendar() {
    isAttendanceCalendarCollapsed = !isAttendanceCalendarCollapsed;
    const content = domCache.attendanceCalendarContent;
    const toggle = domCache.attendanceCalendarToggle;
    if (!content || !toggle) return;
    
    if (isAttendanceCalendarCollapsed) {
        content.classList.add('collapsed');
        toggle.classList.add('collapsed');
    } else {
        content.classList.remove('collapsed');
        toggle.classList.remove('collapsed');
    }
}

function parseTimeToMinutes(value) {
    if (!value) return null;
    const match = String(value).match(/^(\d{1,2}):(\d{2})/);
    if (!match) return null;
    return parseInt(match[1], 10) * 60 + parseInt(match[2], 10);
}

function getAttendanceStatus(record) {
    const status = {
        onDuty: !!record,
        isLate: false,
        isEarlyLeave: false,
        hasOt: false,
    };
    if (!record) return status;

    const rosterIn = parseTimeToMinutes(record.roster_in);
    const rosterOut = parseTimeToMinutes(record.roster_out);
    const inTime = parseTimeToMinutes(record.in_time);
    const outTime = parseTimeToMinutes(record.out_time);
    const otHours = parseFloat(record.ot_hours || 0);

    status.isLate = rosterIn !== null && inTime !== null && inTime > rosterIn;
    status.isEarlyLeave = rosterOut !== null && outTime !== null && outTime < rosterOut;
    status.hasOt = !Number.isNaN(otHours) && otHours > 0;
    return status;
}

function getPendingAttendanceRow(name, location, workDate) {
    return pendingAttendanceRows.find(r => r.nick_name === name && r.location === location && r.work_date === workDate);
}

function getExistingAttendanceRecord(workDate) {
    return currentAttendanceRecords.find(r => r.work_date === workDate);
}

function updateAttendanceCalendarSummary() {
    const monthLabel = document.getElementById('attendance_calendar_month');
    const summary = document.getElementById('attendance_selected_dates');
    if (monthLabel) monthLabel.textContent = currentMonth || '';
    if (!summary) return;

    const dates = Array.from(selectedAttendanceDates).sort();
    if (dates.length === 0) {
        summary.textContent = '未選取日期';
        return;
    }

    const preview = dates.length <= 3 ? dates.join(', ') : `${dates.slice(0, 3).join(', ')} 等 ${dates.length} 天`;
    summary.textContent = `已選 ${dates.length} 天: ${preview}`;
}

function clearAttendanceCalendarSelection() {
    selectedAttendanceDates.clear();
    updateAttendanceCalendarSummary();
    renderAttendanceCalendar(getActiveAttName(), getActiveAttLoc(), currentAttendanceRecords);
}

function focusAttendanceRowByDate(workDate) {
    document.querySelectorAll('#daily_records_body tr').forEach(row => row.classList.remove('attendance-row-focus'));
    const row = document.querySelector(`#daily_records_body tr[data-att-date="${workDate}"]`);
    if (!row) return;
    row.classList.add('attendance-row-focus');
    row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    window.setTimeout(() => row.classList.remove('attendance-row-focus'), 1800);
}

function toggleAttendanceCalendarDate(workDate) {
    if (!workDate) return;
    if (selectedAttendanceDates.has(workDate)) selectedAttendanceDates.delete(workDate);
    else selectedAttendanceDates.add(workDate);

    const dateInput = document.getElementById('new_date');
    if (dateInput) dateInput.value = workDate;

    if (getExistingAttendanceRecord(workDate)) {
        focusAttendanceRowByDate(workDate);
    }

    updateAttendanceCalendarSummary();
    renderAttendanceCalendar(getActiveAttName(), getActiveAttLoc(), currentAttendanceRecords);
}

function applyAttendanceSelectionBulk() {
    const name = getActiveAttName();
    const location = getActiveAttLoc();
    if (!name || !location) {
        alert('請先選擇推廣員與地點。');
        return;
    }
    if (selectedAttendanceDates.size === 0) {
        alert('請先在月曆中選擇日期。');
        return;
    }

    const inInput = document.getElementById('new_in').value;
    const outInput = document.getElementById('new_out').value;
    const normalInput = parseFloat(document.getElementById('new_normal').value || 8.0);
    const rosterIn = document.getElementById('new_roster_in') ? document.getElementById('new_roster_in').value : '';
    const rosterOut = document.getElementById('new_roster_out') ? document.getElementById('new_roster_out').value : '';

    if (!inInput || !outInput) {
        alert('請先填好下方新增列的實際簽到與簽退時間。');
        return;
    }

    let createdCount = 0;
    let updatedPendingCount = 0;
    let skippedExistingCount = 0;

    Array.from(selectedAttendanceDates).sort().forEach(workDate => {
        const existing = getExistingAttendanceRecord(workDate);
        if (existing) {
            skippedExistingCount++;
            return;
        }

        const pending = getPendingAttendanceRow(name, location, workDate);
        if (pending) {
            pending.roster_in = rosterIn || undefined;
            pending.roster_out = rosterOut || undefined;
            pending.in_time = inInput;
            pending.out_time = outInput;
            pending.normal_hours = normalInput;
            updatedPendingCount++;
            return;
        }

        pendingAttendanceRows.push({
            nick_name: name,
            work_date: workDate,
            location: location,
            roster_in: rosterIn || undefined,
            roster_out: rosterOut || undefined,
            in_time: inInput,
            out_time: outInput,
            normal_hours: normalInput,
        });
        createdCount++;
    });

    refreshDailyTable(name, location);
    updateSaveAllButtons();

    const messages = [];
    if (createdCount > 0) messages.push(`新增待儲存 ${createdCount} 天`);
    if (updatedPendingCount > 0) messages.push(`更新暫存 ${updatedPendingCount} 天`);
    if (skippedExistingCount > 0) messages.push(`略過已有紀錄 ${skippedExistingCount} 天`);
    alert(messages.length ? `✅ 批量套用完成：${messages.join('；')}` : '沒有可套用的日期。');
}

function renderAttendanceCalendar(name, location, data) {
    const grid = domCache.attendanceCalendarGrid;
    const hint = document.getElementById('attendance_calendar_hint');
    if (!grid) return;

    updateAttendanceCalendarSummary();

    if (!name || !location) {
        if (hint) hint.textContent = '請先選擇上方推廣員與地點。';
        grid.innerHTML = '<div class="col-span-7 py-8 text-center text-sm text-slate-500">請先選擇推廣員與地點以載入月曆。</div>';
        return;
    }

    if (hint) {
        hint.textContent = '點日期可選取；若該日已有紀錄會自動定位到下方表格。再按「套用下方新增欄位到已選日期」可批量建立暫存。';
    }

    const [yearText, monthText] = (currentMonth || '').split('-');
    const year = parseInt(yearText, 10);
    const month = parseInt(monthText, 10);
    if (!year || !month) {
        grid.innerHTML = '<div class="col-span-7 py-8 text-center text-sm text-slate-500">月份資料無效。</div>';
        return;
    }

    const firstDay = new Date(year, month - 1, 1);
    const daysInMonth = new Date(year, month, 0).getDate();
    const startWeekday = firstDay.getDay();
    const today = new Date();
    const todayText = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

    let html = '';
    for (let i = 0; i < startWeekday; i++) {
        html += '<div class="attendance-calendar-cell is-empty"></div>';
    }

    for (let day = 1; day <= daysInMonth; day++) {
        const workDate = `${currentMonth}-${String(day).padStart(2, '0')}`;
        const record = data.find(r => r.work_date === workDate);
        const pending = getPendingAttendanceRow(name, location, workDate);
        const status = getAttendanceStatus(record);

        const classes = ['attendance-calendar-cell'];
        if (status.onDuty) classes.push('has-duty');
        if (status.isLate) classes.push('has-late');
        if (status.isEarlyLeave) classes.push('has-early');
        if (status.hasOt) classes.push('has-ot');
        if (pending) classes.push('has-pending');
        if (selectedAttendanceDates.has(workDate)) classes.push('is-selected');
        if (workDate === todayText) classes.push('is-today');

        const badges = [];
        if (pending) badges.push('<span class="attendance-calendar-badge is-pending">待儲存</span>');
        else if (status.onDuty) badges.push('<span class="attendance-calendar-badge is-duty">On Duty</span>');
        if (status.isLate) badges.push('<span class="attendance-calendar-badge is-late">遲到</span>');
        if (status.isEarlyLeave) badges.push('<span class="attendance-calendar-badge is-early">早退</span>');
        if (status.hasOt) badges.push('<span class="attendance-calendar-badge is-ot">OT</span>');

        let meta = '';
        if (record) {
            meta = `<span class="attendance-calendar-meta">${(record.in_time || '--:--').substring(0, 5)}<br>~<br>${(record.out_time || '--:--').substring(0, 5)}</span>`;
        } else if (pending) {
            meta = `<span class="attendance-calendar-meta">${pending.in_time || '--:--'}<br>~<br>${pending.out_time || '--:--'}</span>`;
        }

        html += `
            <button type="button" class="${classes.join(' ')}" onclick="toggleAttendanceCalendarDate('${workDate}')">
                <span class="attendance-calendar-date"><span>${day}</span><span class="text-slate-500 text-[10px]">${selectedAttendanceDates.has(workDate) ? '已選' : ''}</span></span>
                <span class="attendance-calendar-body">${meta}<span class="attendance-calendar-badges">${badges.join('')}</span></span>
            </button>
        `;
    }

    grid.innerHTML = html;
}

// ── 格式化小幫手：自動將 Excel 貼上的日期與時間標準化 ──
function formatPasteDate(raw) {
    if (!raw) return '';
    // 如果已經是 YYYY-MM-DD 格式，直接回傳
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
    
    // 處理 Excel 常見的 D/M/YYYY 或 DD/MM/YYYY
    const parts = raw.split(/[\/\-]/);
    if (parts.length === 3) {
        if (parts[2].length === 4) { 
            // 年份在後 (例如 1/7/2026 -> 2026-07-01)
            return `${parts[2]}-${parts[1].padStart(2, '0')}-${parts[0].padStart(2, '0')}`;
        } else if (parts[0].length === 4) { 
            // 年份在前 (例如 2026/7/1 -> 2026-07-01)
            return `${parts[0]}-${parts[1].padStart(2, '0')}-${parts[2].padStart(2, '0')}`;
        }
    }
    return raw;
}

function formatPasteTime(raw) {
    if (!raw) return '';
    // 只抓取字串前面的 HH:MM，過濾掉秒數 (例如 12:00:00 -> 12:00)
    const match = raw.trim().match(/^(\d{1,2}):(\d{2})/);
    if (match) {
        return `${match[1].padStart(2, '0')}:${match[2]}`;
    }
    return raw;
}

// ── Helper：從下拉選單取得當前選取的員工與地點 ──
function getActiveAttName() { return domCache.attModalPromoter ? domCache.attModalPromoter.value : ''; }
function getActiveAttLoc() { return domCache.attModalLoc ? domCache.attModalLoc.value : ''; }
function getActiveSalesName() { const el = document.getElementById('sales_modal_promoter'); return el ? el.value : ''; }
function getActiveSalesLoc() { const el = document.getElementById('sales_modal_loc'); return el ? el.value : ''; }

// ==========================================
// 考勤視窗邏輯
// ==========================================

function openNewAttendanceModal() {
    currentAttendanceRecords = [];
    selectedAttendanceDates.clear();
    isAttendanceCalendarCollapsed = true;
    const content = document.getElementById('attendanceCalendarContent');
    const toggle = document.getElementById('attendanceCalendarToggle');
    if (content) content.classList.add('collapsed');
    if (toggle) toggle.classList.add('collapsed');
    document.getElementById('att_modal_promoter').value = '';
    document.getElementById('att_modal_loc').value = '';
    reorderLocationDropdown('att_modal_loc', []);
    document.getElementById('att_name_hidden').value = '';
    document.getElementById('att_loc_hidden').value = '';
    const nl = document.getElementById('new_loc');
    if (nl) nl.value = '';
    ['att_exp','att_adj','att_bonus','att_monthly_hr','att_monthly_salary'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
    });
    const hint = document.getElementById('att_hr_hint');
    if (hint) hint.innerHTML = 'ℹ️ 請先選擇推廣員以檢視預設時薪';
    const salHint = document.getElementById('att_salary_hint');
    if (salHint) salHint.innerHTML = '';
    const newRosterIn = document.getElementById('new_roster_in');
    if (newRosterIn) newRosterIn.value = '12:00';
    const newRosterOut = document.getElementById('new_roster_out');
    if (newRosterOut) newRosterOut.value = '20:00';
    const newIn = document.getElementById('new_in');
    if (newIn) newIn.value = '12:00';
    const newOut = document.getElementById('new_out');
    if (newOut) newOut.value = '20:00';
    const newNormal = document.getElementById('new_normal');
    if (newNormal) newNormal.value = '8.0';
    setDateRange(document.getElementById('new_date'), currentMonth, true);
    const tbody = document.getElementById('daily_records_body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-500 py-6">請完整選擇上方「推廣員」與「地點」以開始新增紀錄。</td></tr>';
    renderAttendanceCalendar('', '', []);
    updateSaveAllButtons();
    openModal('attendanceModal');
}

function handleAttModalChange() {
    if (handleAttModalChangeDebounced) {
        handleAttModalChangeDebounced();
    }
}

function handleAttModalChangeImpl() {
    const name = getActiveAttName();
    const location = getActiveAttLoc();
    
    // 💡 觸發考勤地點排序 (包含資料庫已有的 + 剛暫存的)
    const attLocMap = getLocMap('att-loc-map');
    const activeAttLocs = Array.from(new Set([...(attLocMap[name] || []), ...pendingAttendanceRows.filter(r => r.nick_name === name).map(r => r.location)]));
    reorderLocationDropdown('att_modal_loc', activeAttLocs);
    
    const sel = document.getElementById('att_modal_promoter');
    const opt = sel ? sel.options[sel.selectedIndex] : null;
    const defaultHr = opt ? (parseFloat(opt.getAttribute('data-hr')) || 0) : 0;
    const hint = document.getElementById('att_hr_hint');
    const hrInp = document.getElementById('att_monthly_hr');
    if (name) {
        if (hint) hint.innerHTML = `ℹ️ 該員工預設：$${defaultHr}`;
        if (hrInp) hrInp.placeholder = `預設 $${defaultHr}`;
    } else {
        if (hint) hint.innerHTML = 'ℹ️ 請先選擇推廣員以檢視預設時薪';
        if (hrInp) hrInp.placeholder = '';
    }
    document.getElementById('att_name_hidden').value = name;
    document.getElementById('att_loc_hidden').value = location;
    const nl = document.getElementById('new_loc');
    if (nl) nl.value = location;

    if (domCache.dailyRecordsBody) {
        if (name && location) {
            if (domCache.dailyRecordsBody) domCache.dailyRecordsBody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-400 py-6">載入中...</td></tr>';
            refreshDailyTable(name, location);
        } else if (domCache.dailyRecordsBody) {
            domCache.dailyRecordsBody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-500 py-6">請完整選擇上方「推廣員」與「地點」以載入資料。</td></tr>';
            currentAttendanceRecords = [];
            selectedAttendanceDates.clear();
            renderAttendanceCalendar('', '', []);
        }
    }
    updateSaveAllButtons();
}

function editAttendance(name, loc, days, hours, ot, exp, adj, bonus, monthly_hr, default_hr, monthly_sal, default_sal) {
    currentAttendanceRecords = [];
    selectedAttendanceDates.clear();
    document.getElementById('att_modal_promoter').value = name;
    document.getElementById('att_modal_loc').value = loc;
    const attLocMap = getLocMap('att-loc-map');
    reorderLocationDropdown('att_modal_loc', attLocMap[name] || []);
    document.getElementById('att_name_hidden').value = name;
    document.getElementById('att_loc_hidden').value = loc;
    const nl = document.getElementById('new_loc');
    if (nl) nl.value = loc;

    setDateRange(document.getElementById('new_date'), currentMonth, true);
    document.getElementById('att_exp').value = exp || 0;
    document.getElementById('att_adj').value = adj || 0;
    document.getElementById('att_bonus').value = bonus || 0;

    const hrInput = document.getElementById('att_monthly_hr');
    hrInput.value = (monthly_hr !== null && monthly_hr !== undefined) ? monthly_hr : '';
    hrInput.placeholder = `預設 $${default_hr}`;
    const hrHint = document.getElementById('att_hr_hint');
    if (hrHint) hrHint.innerHTML = `ℹ️ 該員工預設：$${default_hr}`;

    // 本月專屬月薪
    const salInput = document.getElementById('att_monthly_salary');
    if (salInput) {
        salInput.value = (monthly_sal !== null && monthly_sal !== undefined) ? monthly_sal : '';
        salInput.placeholder = default_sal ? `預設 $${default_sal}` : '';
    }
    const salHint = document.getElementById('att_salary_hint');
    if (salHint) {
        salHint.innerHTML = default_sal ? `ℹ️ 預設：$${default_sal}` : '';
    }

    const tbody = document.getElementById('daily_records_body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-400 py-6">載入中...</td></tr>';
    refreshDailyTable(name, loc);
    updateSaveAllButtons();
    openModal('attendanceModal');
}

// ==========================================
// 銷售視窗邏輯
// ==========================================

function openNewSalesModal() {
    document.getElementById('sales_modal_promoter').value = '';
    document.getElementById('sales_modal_loc').value = '';
    reorderLocationDropdown('sales_modal_loc', []);
    const nsl = document.getElementById('new_sales_loc');
    if (nsl) nsl.value = '';
    const ci = document.getElementById('sales_monthly_comm_input');
    if (ci) { ci.value = ''; ci.placeholder = '留空則使用預設'; }
    const ch = document.getElementById('sales_comm_hint');
    if (ch) ch.innerHTML = 'ℹ️ 請先選擇推廣員';
    setDateRange(document.getElementById('new_sales_date'), currentMonth, true);
    const tbody = document.getElementById('sales_records_body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="text-center text-slate-500 py-6">請完整選擇上方「推廣員」與「地點」以開始新增單據。</td></tr>';
    updateSaveAllButtons();
    openModal('salesModal');
}

function handleSalesModalChange() {
    if (handleSalesModalChangeDebounced) {
        handleSalesModalChangeDebounced();
    }
}

function handleSalesModalChangeImpl() {
    const name = getActiveSalesName();
    const location = getActiveSalesLoc();
    
    // 💡 觸發銷售地點排序
    const salesLocMap = getLocMap('sales-loc-map');
    const activeSalesLocs = Array.from(new Set([...(salesLocMap[name] || []), ...pendingSalesRows.filter(r => r.promoter_name === name).map(r => r.location)]));
    reorderLocationDropdown('sales_modal_loc', activeSalesLocs);
    
    const sel = document.getElementById('sales_modal_promoter');
    const opt = sel ? sel.options[sel.selectedIndex] : null;
    const defaultComm = opt ? (parseFloat(opt.getAttribute('data-comm')) || 0) : 0;
    const hint = document.getElementById('sales_comm_hint');
    const ci = document.getElementById('sales_monthly_comm_input');

    if (name) {
        const pct = (defaultComm * 100).toFixed(0);
        if (hint) hint.innerHTML = `ℹ️ 該員工預設：${pct}%`;
        if (ci) ci.placeholder = `預設 ${defaultComm}`;
    } else {
        if (hint) hint.innerHTML = 'ℹ️ 請先選擇推廣員';
        if (ci) ci.placeholder = '';
    }

    const nsl = document.getElementById('new_sales_loc');
    if (nsl) nsl.value = location;

    const tbody = document.getElementById('sales_records_body');
    if (name && location) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="text-center text-slate-400 py-6">載入中...</td></tr>';
        refreshSalesTable(name, location);
    } else if (tbody) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-slate-500 py-6">請完整選擇上方「推廣員」與「地點」以載入資料。</td></tr>';
    }
    updateSaveAllButtons();
}

function openSalesModal(name, location, monthlyComm, defaultComm) {
    document.getElementById('sales_modal_promoter').value = name;
    document.getElementById('sales_modal_loc').value = location;
    const salesLocMap = getLocMap('sales-loc-map');
    reorderLocationDropdown('sales_modal_loc', salesLocMap[name] || []);

    const locSelect = document.getElementById('new_sales_loc');
    if (locSelect) locSelect.value = location;

    const commInput = document.getElementById('sales_monthly_comm_input');
    commInput.value = (monthlyComm !== null && monthlyComm !== undefined) ? monthlyComm : '';
    commInput.placeholder = `預設 ${defaultComm}`;

    const hintEl = document.getElementById('sales_comm_hint');
    if (hintEl) hintEl.innerHTML = `ℹ️ 該員工預設：${(defaultComm * 100).toFixed(0)}%`;

    setDateRange(document.getElementById('new_sales_date'), currentMonth, true);
    const tbody = document.getElementById('sales_records_body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-slate-400">正在撈取該店銷售紀錄...</td></tr>';
    updateSaveAllButtons();
    openModal('salesModal');
    refreshSalesTable(name, location);
}

function saveSalesComm() {
    const name = getActiveSalesName();
    if (!name) { alert('請先選擇推廣員'); return; }
    const commValue = document.getElementById('sales_monthly_comm_input').value;
    const formData = new FormData();
    formData.append('month', currentMonth);
    formData.append('promoter', name);
    formData.append('monthly_comm', commValue);

    fetch('/update_monthly_comm_api', { method: 'POST', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                alert('✅ 月度佣金設定已儲存！關閉視窗後將重新整理。');
            }
        });
}

function clearAttendanceEditModal() {
    // Clear pending rows for this employee + location
    const name = getActiveAttName();
    const location = getActiveAttLoc();
    if (name && location) {
        pendingAttendanceRows = pendingAttendanceRows.filter(r => !(r.nick_name === name && r.location === location));
    }
    currentAttendanceRecords = [];
    selectedAttendanceDates.clear();
    // Clear daily records table body
    const tbody = document.getElementById('daily_records_body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-500 py-6">尚無紀錄。</td></tr>';
    // Clear adjustment form fields
    const fields = ['att_name_hidden', 'att_loc_hidden', 'att_monthly_hr', 'att_monthly_salary', 'att_exp', 'att_bonus', 'att_adj'];
    fields.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const hrHint = document.getElementById('att_hr_hint');
    if (hrHint) hrHint.textContent = '';
    const salHint = document.getElementById('att_salary_hint');
    if (salHint) salHint.textContent = '';
    renderAttendanceCalendar('', '', []);
    updateSaveAllButtons();
}

function clearSalesEditModal() {
    // Clear pending rows for this employee + location
    const name = getActiveSalesName();
    const location = getActiveSalesLoc();
    if (name && location) {
        pendingSalesRows = pendingSalesRows.filter(r => !(r.promoter_name === name && r.location === location));
    }
    // Clear sales records table body
    const tbody = document.getElementById('sales_records_body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-slate-500">正在載入數據...</td></tr>';
    // Clear sales form fields
    const commInput = document.getElementById('sales_monthly_comm_input');
    if (commInput) commInput.value = '';
    const commHint = document.getElementById('sales_comm_hint');
    if (commHint) commHint.textContent = '';
    updateSaveAllButtons();
}

function getMonthDateRange(monthStr) {
    if (!monthStr) {
        return { min: '', max: '', defaultValue: '' };
    }
    const [year, monthNum] = monthStr.split('-');
    const lastDay = new Date(year, monthNum, 0).getDate();
    const min = `${monthStr}-01`;
    const max = `${monthStr}-${String(lastDay).padStart(2, '0')}`;
    return { min, max, defaultValue: min };
}

function setDateRange(input, monthStr, withDefault = false) {
    if (!input) {
        return;
    }
    const range = getMonthDateRange(monthStr);
    input.min = range.min;
    input.max = range.max;
    if (withDefault) {
        input.value = range.defaultValue;
    }
}

function refreshDailyTable(name, location) {
    fetch(`/api/daily_attendance/${currentMonth}/${encodeURIComponent(name)}/${encodeURIComponent(location)}`)
        .then(response => response.json())
        .then(data => {
            currentAttendanceRecords = Array.isArray(data) ? data : [];
            const tbody = document.getElementById('daily_records_body');
            tbody.innerHTML = '';

            if (data.length === 0) {
                tbody.innerHTML = '';
                renderPendingAttendanceRows(tbody, name, location);
                renderAttendanceCalendar(name, location, currentAttendanceRecords);
                return;
            }

            data.forEach((record, index) => {
                let inTimeColor = "text-slate-200";
                let outTimeColor = "text-slate-200";
                let warningBadge = "";

                // 統一 substring(0,5) 濾除秒數，確保比較基準一致
                const rIn = (record.roster_in || '').substring(0, 5);
                const rOut = (record.roster_out || '').substring(0, 5);
                const aIn = (record.in_time || '').substring(0, 5);
                const aOut = (record.out_time || '').substring(0, 5);

                if (rIn && aIn && aIn > rIn) {
                    inTimeColor = "text-red-400 font-bold bg-red-900/30";
                    warningBadge += `<span class="block text-[10px] text-red-400">遲到</span>`;
                }
                if (rOut && aOut && aOut < rOut) {
                    outTimeColor = "text-amber-400 font-bold bg-amber-900/30";
                    warningBadge += `<span class="block text-[10px] text-amber-400">早退</span>`;
                }

                const tr = document.createElement('tr');
                tr.setAttribute('data-att-id', record.id);
                tr.setAttribute('data-att-date', record.work_date);
                tr.innerHTML = `
                    <td class="text-center text-sm text-slate-500 align-middle">${index + 1}</td>
                    <td class="text-center font-bold text-sm align-middle">${record.work_date}</td>
                    <td class="text-center align-middle"><span class="inline-flex items-center px-2 py-0.5 rounded-full text-sm font-medium bg-slate-700 text-slate-200">${record.location}</span><br>${warningBadge}</td>

                    <td class="px-1 py-1.5 align-middle">
                        <div class="space-y-1">
                            <input type="time" class="edit-roster-in bg-slate-800/50 border border-slate-600 rounded px-1.5 py-1 text-xs text-indigo-300 w-full" value="${rIn}">
                            <input type="time" class="edit-roster-out bg-slate-800/50 border border-slate-600 rounded px-1.5 py-1 text-xs text-indigo-300 w-full" value="${rOut}">
                        </div>
                    </td>

                    <td class="px-1 py-1.5 align-middle">
                        <div class="space-y-1">
                            <input type="time" class="edit-in-time ${inTimeColor} border border-slate-600 rounded px-1.5 py-1 text-xs w-full" value="${aIn}">
                            <input type="time" class="edit-out-time ${outTimeColor} border border-slate-600 rounded px-1.5 py-1 text-xs w-full" value="${aOut}">
                        </div>
                    </td>

                    <td class="px-1 py-1.5 align-middle">
                        <input type="number" step="0.5" class="edit-normal-hours bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200 w-full" value="${parseFloat(record.normal_hours || 8.0).toFixed(1)}">
                    </td>
                    <td class="text-center font-bold text-sm align-middle">${parseFloat(record.actual_hours).toFixed(2)}</td>
                    <td class="text-center text-red-400 text-sm align-middle">${parseFloat(record.ot_hours).toFixed(2)}</td>
                    <td class="text-center align-middle">
                        <div class="flex flex-col gap-1 justify-center">
                            <button type="button" class="bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-medium py-1 px-2 rounded transition-colors" onclick="saveDailyRecord(${record.id}, '${name}', '${location}')">💾 修改</button>
                            <button type="button" class="border border-red-800/50 text-red-400 hover:bg-red-900/30 text-[11px] font-medium py-1 px-2 rounded transition-colors" onclick="deleteRecord(${record.id}, '${name}', '${location}')">🗑️ 刪除</button>
                        </div>
                    </td>
                `;
                tbody.appendChild(tr);
            });
            // Append pending rows (not yet saved to DB)
            renderPendingAttendanceRows(tbody, name, location);
            renderAttendanceCalendar(name, location, currentAttendanceRecords);
        });
}

function deleteRecord(id, name, location) {
    if (confirm('確定要永久刪除這筆單日考勤嗎？此動作無法復原。')) {
        fetch(`/delete_daily_attendance/${id}`, { method: 'POST' })
            .then(response => response.json())
            .then(result => {
                if (result.status === 'success') {
                    refreshDailyTable(name, location);
                }
            });
    }
}

function saveDailyRecord(id, name, location) {
    const row = document.querySelector(`tr[data-att-id="${id}"]`);
    if (!row) return;

    const rosterIn = row.querySelector('.edit-roster-in').value;
    const rosterOut = row.querySelector('.edit-roster-out').value;
    const inTime = row.querySelector('.edit-in-time').value;
    const outTime = row.querySelector('.edit-out-time').value;
    const normalHrs = row.querySelector('.edit-normal-hours').value;

    if (!inTime || !outTime) {
        alert('請完整填寫實際簽到與簽退時間！');
        return;
    }

    const formData = new FormData();
    formData.append('id', id);
    formData.append('roster_in', rosterIn);
    formData.append('roster_out', rosterOut);
    formData.append('in_time', inTime);
    formData.append('out_time', outTime);
    formData.append('normal_hours', normalHrs || 8.0);

    fetch('/update_daily_record_api', { method: 'POST', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                refreshDailyTable(name, location);
            } else {
                alert(result.message || '更新失敗');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('更新發生錯誤，請稍後再試');
        });
}

function addNewRecordFromUI() {
    const name = getActiveAttName();
    const location = getActiveAttLoc();
    const dateInput = document.getElementById('new_date').value;
    const inInput = document.getElementById('new_in').value;
    const outInput = document.getElementById('new_out').value;
    const normalInput = document.getElementById('new_normal').value;
    const ri = document.getElementById('new_roster_in') ? document.getElementById('new_roster_in').value : '';
    const ro = document.getElementById('new_roster_out') ? document.getElementById('new_roster_out').value : '';

    if (!dateInput || !inInput || !outInput) {
        alert('請完整填寫日期與時間！');
        return;
    }

    pendingAttendanceRows.push({
        nick_name: name,
        work_date: dateInput,
        location: location,
        roster_in: ri || undefined,
        roster_out: ro || undefined,
        in_time: inInput,
        out_time: outInput,
        normal_hours: parseFloat(normalInput || 8.0),
    });

    // Reset input fields
    const newRosterIn = document.getElementById('new_roster_in');
    if (newRosterIn) newRosterIn.value = '12:00';
    const newRosterOut = document.getElementById('new_roster_out');
    if (newRosterOut) newRosterOut.value = '20:00';
    document.getElementById('new_in').value = '12:00';
    document.getElementById('new_out').value = '20:00';
    document.getElementById('new_normal').value = '8.0';

    // Re-render to show the new pending row
    refreshDailyTable(name, location);
    updateSaveAllButtons();
}

function refreshSalesTable(name, location) {
    fetch(`/api/sales_records/${currentMonth}/${encodeURIComponent(name)}/${encodeURIComponent(location)}`)
        .then(response => response.json())
        .then(data => {
            const tbody = document.getElementById('sales_records_body');
            tbody.innerHTML = '';

            if (data.length === 0) {
                tbody.innerHTML = '';
                renderPendingSalesRows(tbody, name, location);
                return;
            }

            const range = getMonthDateRange(currentMonth);
            data.forEach((record, index) => {
                let safeDate = '';
                if (record.date) {
                    safeDate = String(record.date).replace(/\//g, '-').substring(0, 10);
                }
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="text-center text-sm text-slate-500">${index + 1}</td>
                    <td class="text-center">
                        <input type="date" class="edit-sales-date bg-slate-800 border border-slate-600 rounded-lg px-2 py-1 text-sm text-slate-200 w-full" value="${safeDate}" min="${range.min}" max="${range.max}">
                    </td>
                    <td class="text-center"><span class="inline-flex items-center px-2 py-0.5 rounded-full text-sm font-medium bg-slate-700 text-slate-200">${record.location}</span></td>
                    <td class="text-center">
                        <input list="productModels" type="text" class="edit-sales-model bg-slate-800 border border-slate-600 rounded-lg px-2 py-1 text-sm text-slate-200 w-full" value="${record.model || ''}" placeholder="輸入或選擇型號">
                    </td>
                    <td class="text-center">
                        <input type="number" min="1" class="edit-sales-qty bg-slate-800 border border-slate-600 rounded-lg px-2 py-1 text-sm text-slate-200 w-full" value="${record.quantity || 1}">
                    </td>
                    <td class="text-center">
                        <input type="number" step="0.1" class="edit-sales-price bg-slate-800 border border-slate-600 rounded-lg px-2 py-1 text-sm text-slate-200 w-full" value="${parseFloat(record.price || 0).toFixed(2)}">
                    </td>
                    <td class="text-center">
                        <div class="flex gap-1 justify-center">
                            <button type="button" class="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium py-1 px-2 rounded-lg transition-colors" onclick="saveSalesRecord(${record.id})">💾 修改</button>
                            <button type="button" class="border border-red-800/50 text-red-400 hover:bg-red-900/30 text-sm font-medium py-1 px-2 rounded-lg transition-colors" onclick="deleteSalesRecord(${record.id}, '${name}', '${location}')">🗑️ 刪除</button>
                        </div>
                    </td>
                `;
                tr.setAttribute('data-sales-id', record.id);
                tbody.appendChild(tr);
            });
            // Append pending rows (not yet saved to DB)
            renderPendingSalesRows(tbody, name, location);
        })
        .catch(error => {
            console.error('Error:', error);
            document.getElementById('sales_records_body').innerHTML = '<tr><td colspan="7" class="text-danger py-3">⚠️ 讀取失敗。</td></tr>';
        });
}

function deleteSalesRecord(id, name, location) {
    if (confirm('確定要永久刪除這筆銷售紀錄嗎？')) {
        fetch(`/delete_sales_record/${id}`, { method: 'POST' })
            .then(response => response.json())
            .then(result => {
                if (result.status === 'success') {
                    refreshSalesTable(name, location);
                }
            });
    }
}

function saveSalesRecord(id) {
    const row = document.querySelector(`tr[data-sales-id="${id}"]`);
    if (!row) {
        return;
    }

    const dateValue = row.querySelector('.edit-sales-date').value;
    const modelValue = row.querySelector('.edit-sales-model').value.trim();
    const quantityValue = row.querySelector('.edit-sales-qty').value;
    const priceValue = row.querySelector('.edit-sales-price').value;
    const name = getActiveSalesName();
    const location = getActiveSalesLoc();

    if (!modelValue || !priceValue) {
        alert('請完整填寫「型號」與「單價」！');
        return;
    }

    const formData = new FormData();
    formData.append('id', id);
    formData.append('date', dateValue);
    formData.append('model', modelValue);
    formData.append('quantity', quantityValue);
    formData.append('price', priceValue);
    formData.append('promoter_name', name);
    formData.append('location', location);

    fetch('/update_sales_record', { method: 'POST', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                refreshSalesTable(name, location);
            } else {
                alert(result.message || '更新失敗');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('更新發生錯誤，請稍後再試');
        });
}

function addNewSalesRecordFromUI() {
    const name = getActiveSalesName();
    const location = getActiveSalesLoc();
    const dateInput = document.getElementById('new_sales_date').value;
    const modelInput = document.getElementById('new_sales_model').value;
    const qtyInput = document.getElementById('new_sales_qty').value;
    const priceInput = document.getElementById('new_sales_price').value;

    if (!modelInput || !priceInput) {
        alert('請完整填寫「型號」與「單價」！');
        return;
    }

    pendingSalesRows.push({
        promoter_name: name,
        date: dateInput,
        location: location,
        model: modelInput,
        quantity: parseInt(qtyInput) || 1,
        price: parseFloat(priceInput),
    });

    // Reset input fields
    document.getElementById('new_sales_model').value = '';
    document.getElementById('new_sales_qty').value = '1';
    document.getElementById('new_sales_price').value = '';

    // Re-render to show the new pending row
    refreshSalesTable(name, location);
    updateSaveAllButtons();
}

// ── 批次寫入與暫存渲染 ──

function renderPendingAttendanceRows(tbody, name, location) {
    const filtered = pendingAttendanceRows.filter(r => r.nick_name === name && r.location === location);
    if (filtered.length === 0 && tbody.children.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-slate-500 py-3 text-center text-sm">此地點尚無打卡明細。</td></tr>';
        return;
    }
    filtered.forEach((row, i) => {
        const tr = document.createElement('tr');
        tr.className = 'bg-amber-900/40 border-b border-amber-800/30';
        tr.innerHTML = `
            <td class="text-center text-sm text-amber-300 font-bold">⏳</td>
            <td class="text-center font-bold text-sm text-amber-100">${row.work_date}</td>
            <td class="text-center"><span class="inline-flex items-center px-2 py-0.5 rounded-full text-sm font-medium bg-amber-900/60 text-amber-100">${row.location}</span></td>
            <td class="text-center text-sm text-amber-100">${row.roster_in || '—'}<br><span class="text-xs text-amber-700">~</span><br>${row.roster_out || '—'}</td>
            <td class="text-center text-sm text-amber-100 font-medium">${row.in_time}<br><span class="text-xs text-amber-700">~</span><br>${row.out_time}</td>
            <td class="text-center text-sm text-amber-100 font-medium">${row.normal_hours.toFixed(1)}</td>
            <td class="text-center text-sm text-amber-300">—</td>
            <td class="text-center text-sm text-amber-300">—</td>
            <td class="text-center">
                <button type="button" class="border border-red-800/50 text-red-400 hover:bg-red-900/30 text-sm font-medium py-1 px-2 rounded-lg transition-colors"
                    onclick="removePendingAttendance('${location}', ${i})">✕</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function removePendingAttendance(location, index) {
    const name = getActiveAttName();
    const filtered = pendingAttendanceRows.filter(r => r.nick_name === name && r.location === location);
    if (index < filtered.length) {
        const row = filtered[index];
        const globalIdx = pendingAttendanceRows.indexOf(row);
        if (globalIdx !== -1) pendingAttendanceRows.splice(globalIdx, 1);
    }
    // Re-render
    refreshDailyTable(name, location);
    updateSaveAllButtons();
}

function renderPendingSalesRows(tbody, name, location) {
    const filtered = pendingSalesRows.filter(r => r.promoter_name === name && r.location === location);
    if (filtered.length === 0 && tbody.children.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-slate-500 py-3 text-center text-sm">此地點尚無銷售紀錄。</td></tr>';
        return;
    }
    filtered.forEach((row, i) => {
        const tr = document.createElement('tr');
        tr.className = 'bg-amber-900/20';
        tr.innerHTML = `
            <td class="text-center text-sm text-amber-400">⏳</td>
            <td class="text-center text-sm text-amber-200">${row.date || '—'}</td>
            <td class="text-center"><span class="inline-flex items-center px-2 py-0.5 rounded-full text-sm font-medium bg-amber-900/50 text-amber-200">${row.location}</span></td>
            <td class="text-center text-sm text-amber-200">${row.model}</td>
            <td class="text-center text-sm text-amber-200">${row.quantity}</td>
            <td class="text-center text-sm text-amber-200">$${row.price.toFixed(2)}</td>
            <td class="text-center">
                <button type="button" class="border border-red-800/50 text-red-400 hover:bg-red-900/30 text-sm font-medium py-1 px-2 rounded-lg transition-colors"
                    onclick="removePendingSales('${location}', ${i})">✕</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function removePendingSales(location, index) {
    const name = getActiveSalesName();
    const filtered = pendingSalesRows.filter(r => r.promoter_name === name && r.location === location);
    if (index < filtered.length) {
        const row = filtered[index];
        const globalIdx = pendingSalesRows.indexOf(row);
        if (globalIdx !== -1) pendingSalesRows.splice(globalIdx, 1);
    }
    refreshSalesTable(name, location);
    updateSaveAllButtons();
}

async function saveAllAttendanceRecords() {
    const name = getActiveAttName();
    const location = getActiveAttLoc();
    const rows = pendingAttendanceRows.filter(r => r.nick_name === name && r.location === location);

    if (rows.length === 0) {
        alert('沒有待儲存的打卡紀錄。');
        return;
    }

    const btn = document.getElementById('saveAllAttBtn');
    if (btn) { btn.disabled = true; btn.textContent = '儲存中...'; }

    let successCount = 0;
    for (const row of rows) {
        const formData = new FormData();
        formData.append('payroll_month', currentMonth);
        formData.append('nick_name', name);
        formData.append('location', row.location);
        formData.append('work_date', row.work_date);
        formData.append('roster_in', row.roster_in || '');
        formData.append('roster_out', row.roster_out || '');
        formData.append('roster_in', row.roster_in || '');
        formData.append('roster_out', row.roster_out || '');
        formData.append('in_time', row.in_time);
        formData.append('out_time', row.out_time);
        formData.append('normal_hours', row.normal_hours);
        try {
            const resp = await fetch('/add_daily_attendance', { method: 'POST', body: formData });
            const result = await resp.json();
            if (result.status === 'success') successCount++;
        } catch (e) { /* continue */ }
    }

    // Remove saved rows from pending
    pendingAttendanceRows = pendingAttendanceRows.filter(r => !(r.nick_name === name && r.location === location));
    refreshDailyTable(name, location);

    if (btn) { btn.disabled = false; btn.textContent = '💾 儲存全部打卡紀錄'; }
    alert(`✅ 已成功儲存 ${successCount}/${rows.length} 筆打卡紀錄！`);
    updateSaveAllButtons();
}

async function saveAllSalesRecords() {
    const name = getActiveSalesName();
    const location = getActiveSalesLoc();
    const rows = pendingSalesRows.filter(r => r.promoter_name === name && r.location === location);

    if (rows.length === 0) {
        alert('沒有待儲存的銷售單據。');
        return;
    }

    const btn = document.getElementById('saveAllSalesBtn');
    if (btn) { btn.disabled = true; btn.textContent = '儲存中...'; }

    let successCount = 0;
    for (const row of rows) {
        const formData = new FormData();
        formData.append('payroll_month', currentMonth);
        formData.append('promoter_name', name);
        formData.append('date', row.date);
        formData.append('location', row.location);
        formData.append('model', row.model);
        formData.append('quantity', row.quantity);
        formData.append('price', row.price);
        try {
            const resp = await fetch('/add_sales_record', { method: 'POST', body: formData });
            const result = await resp.json();
            if (result.status === 'success') successCount++;
        } catch (e) { /* continue */ }
    }

    // Remove saved rows from pending
    pendingSalesRows = pendingSalesRows.filter(r => !(r.promoter_name === name && r.location === location));
    refreshSalesTable(name, location);

    if (btn) { btn.disabled = false; btn.textContent = '💾 儲存全部單據'; }
    alert(`✅ 已成功儲存 ${successCount}/${rows.length} 筆銷售單據！`);
    updateSaveAllButtons();
}

function updateSaveAllButtons() {
    const attName = getActiveAttName();
    const attLocation = getActiveAttLoc();
    const attCount = pendingAttendanceRows.filter(r => r.nick_name === attName && r.location === attLocation).length;

    const salesName = getActiveSalesName();
    const salesLocation = getActiveSalesLoc();
    const salesCount = pendingSalesRows.filter(r => r.promoter_name === salesName && r.location === salesLocation).length;

    const attBtn = document.getElementById('saveAllAttBtn');
    if (attBtn) {
        attBtn.textContent = attCount > 0 ? `💾 儲存全部打卡紀錄 (${attCount} 筆)` : '💾 儲存全部打卡紀錄';
        attBtn.classList.toggle('hidden', attCount === 0);
    }

    const salesBtn = document.getElementById('saveAllSalesBtn');
    if (salesBtn) {
        salesBtn.textContent = salesCount > 0 ? `💾 儲存全部單據 (${salesCount} 筆)` : '💾 儲存全部單據';
        salesBtn.classList.toggle('hidden', salesCount === 0);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    // 已改用 Tailwind modal（手動 closeModal），不再依賴 Bootstrap hidden.bs.modal 事件
});

// ── Excel 批次貼上：考勤 Modal ──
(function() {
    const attModal = document.getElementById('attendanceModal');
    if (attModal) {
        attModal.addEventListener('paste', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
            const data = (e.clipboardData || window.clipboardData).getData('Text');
            if (!data) return;
            const name = getActiveAttName();
            if (!name) return;
            const location = getActiveAttLoc();
            if (!location) return;

            const lines = data.split('\n');
            let count = 0;
            lines.forEach(row => {
                if (!row.trim()) return;
                const cols = row.split('\t').map(c => c.trim());
                if (cols[0].toLowerCase().includes('date')) return; // 自動跳過標題列

                if (cols.length >= 11) { // 確保有足夠的欄位
                    pendingAttendanceRows.push({
                        nick_name: name, // 維持使用畫面上選定的名字
                        work_date: formatPasteDate(cols[0]),
                        location: cols[2] || location,
                        in_time: formatPasteTime(cols[4]),         // 實際簽到
                        out_time: formatPasteTime(cols[5]),        // 實際簽退
                        roster_in: formatPasteTime(cols[8]),       // 表定簽到
                        roster_out: formatPasteTime(cols[9]),      // 表定簽退
                        normal_hours: parseFloat(cols[10] || 8.0), // 常規工時
                    });
                    count++;
                }
            });
            if (count > 0) {
                refreshDailyTable(name, location);
                updateSaveAllButtons();
                alert(`✅ 從剪貼簿匯入 ${count} 筆打卡紀錄！請確認後點擊「儲存全部打卡紀錄」。`);
            }
        });
    }

    // ── Excel 批次貼上：銷售 Modal ──
    const salesModalEl = document.getElementById('salesModal');
    if (salesModalEl) {
        salesModalEl.addEventListener('paste', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
            const data = (e.clipboardData || window.clipboardData).getData('Text');
            if (!data) return;
            const name = getActiveSalesName();
            if (!name) return;
            const location = getActiveSalesLoc();
            if (!location) return;

            const lines = data.split('\n');
            let count = 0;
            lines.forEach(row => {
                if (!row.trim()) return;
                const cols = row.split('\t').map(c => c.trim());
                if (cols[0].toLowerCase().includes('shop')) return; // 自動跳過標題列

                if (cols.length >= 10) { // 確保有 10 個欄位
                    let pastedDate = formatPasteDate(cols[4]); // 第 5 欄: date
                    if (/^\d{1,2}$/.test(pastedDate)) {
                        pastedDate = `${currentMonth}-${pastedDate.padStart(2, '0')}`;
                    }

                    // 💡 智慧除錯：如果 Model 是 #N/A，就改抓 Input 欄位 (第 8 欄)
                    let finalModel = cols[5];
                    if (!finalModel || finalModel.toUpperCase() === '#N/A') {
                        finalModel = cols[7]; 
                    }

                    pendingSalesRows.push({
                        promoter_name: name,                
                        location: location,                 
                        date: pastedDate,                   
                        model: finalModel,                  
                        quantity: parseInt(cols[8] || 1),   // 第 9 欄: quantity
                        price: parseFloat(cols[9] || 0),    // 第 10 欄: price
                    });
                    count++;
                }
            });
            if (count > 0) {
                refreshSalesTable(name, location);
                updateSaveAllButtons();
                alert(`✅ 從剪貼簿匯入 ${count} 筆銷售單據！請確認後點擊「儲存全部單據」。`);
            }
        });
    }
})();

// ==========================================
// 🚀 Excel Textarea 批次匯入功能
// ==========================================

function processAttendancePaste() {
    const textarea = document.getElementById('att_bulk_paste');
    const pastedData = textarea.value;
    if (!pastedData.trim()) { alert('請先在文字框內貼上 Excel 資料！'); return; }

    const name = getActiveAttName();
    const location = getActiveAttLoc();
    const rows = pastedData.split('\n');
    let addedCount = 0;

    rows.forEach(row => {
        if (!row.trim()) return;
        const cols = row.split('\t').map(c => c.trim());
        if (cols[0].toLowerCase().includes('date')) return; // 自動跳過標題列

        if (cols.length >= 11) {
            pendingAttendanceRows.push({
                nick_name: name,
                work_date: formatPasteDate(cols[0]),
                location: cols[2] || location,
                in_time: formatPasteTime(cols[4]),         // 實際簽到
                out_time: formatPasteTime(cols[5]),        // 實際簽退
                roster_in: formatPasteTime(cols[8]),       // 表定簽到
                roster_out: formatPasteTime(cols[9]),      // 表定簽退
                normal_hours: parseFloat(cols[10] || 8.0),
            });
            addedCount++;
        }
    });

    if (addedCount > 0) {
        refreshDailyTable(name, location);
        updateSaveAllButtons();
        textarea.value = '';
        alert(`✅ 成功匯入 ${addedCount} 筆打卡資料！請確認後點擊「儲存全部打卡紀錄」。`);
    } else {
        alert('⚠️ 無法解析資料，請檢查貼上的格式是否符合對照表要求（至少 11 欄：Date, Nick Name, Location, Name, In-Time, Out-Time, Hours, OT, In-Time2, Out-Time2, Normal working hours）。');
    }
}

function processSalesPaste() {
    const textarea = document.getElementById('sales_bulk_paste');
    const pastedData = textarea.value;
    if (!pastedData.trim()) { alert('請先在文字框內貼上 Excel 資料！'); return; }

    const name = getActiveSalesName();
    const location = getActiveSalesLoc();
    const rows = pastedData.split('\n');
    let addedCount = 0;

    rows.forEach(row => {
        if (!row.trim()) return;
        const cols = row.split('\t').map(c => c.trim());
        if (cols[0].toLowerCase().includes('shop')) return; // 自動跳過標題列

        if (cols.length >= 10) {
            let pastedDate = formatPasteDate(cols[4]);
            if (/^\d{1,2}$/.test(pastedDate)) {
                pastedDate = `${currentMonth}-${pastedDate.padStart(2, '0')}`;
            }

            let finalModel = cols[5];
            if (!finalModel || finalModel.toUpperCase() === '#N/A') {
                finalModel = cols[7];
            }

            pendingSalesRows.push({
                promoter_name: name,
                location: location,
                date: pastedDate,
                model: finalModel,
                quantity: parseInt(cols[8] || 1),
                price: parseFloat(cols[9] || 0),
            });
            addedCount++;
        }
    });

    if (addedCount > 0) {
        refreshSalesTable(name, location);
        updateSaveAllButtons();
        textarea.value = '';
        alert(`✅ 成功匯入 ${addedCount} 筆銷售單據！請確認後點擊「儲存全部單據」。`);
    } else {
        alert('⚠️ 無法解析資料，請檢查貼上的格式是否符合對照表要求（至少 10 欄）。');
    }
}

// ==========================================
// 🌍 全域跨店批次貼上 (Global Bulk Paste)
// ==========================================

async function executeGlobalAttPaste() {
    const textarea = document.getElementById('global_att_textarea');
    const pastedData = textarea.value;
    if (!pastedData.trim()) { alert('資料區不能為空，請貼上 Excel 資料。'); return; }

    const rows = pastedData.split('\n');
    const parsedRows = [];
    rows.forEach((row, index) => {
        if (!row.trim()) return;
        const cols = row.split('\t').map(c => c.trim());
        if (cols[0].toLowerCase().includes('date')) return; // 自動跳過標題列

        if (cols.length >= 11) { 
            parsedRows.push({
                work_date: formatPasteDate(cols[0]),
                nick_name: cols[1],                        // 從 Excel 抓取名字
                location: cols[2],                         // 從 Excel 抓取地點
                in_time: formatPasteTime(cols[4]),         // 實際簽到
                out_time: formatPasteTime(cols[5]),        // 實際簽退
                roster_in: formatPasteTime(cols[8]),       // 表定簽到
                roster_out: formatPasteTime(cols[9]),      // 表定簽退
                normal_hours: parseFloat(cols[10] || 8.0),
            });
        } else {
            console.warn(`第 ${index + 1} 行欄位不足，已略過:`, row);
        }
    });

    if (parsedRows.length === 0) {
        alert('未能解析出有效的資料，請確認欄位與上方格式相符。');
        return;
    }

    if (!confirm(`解析成功！共讀取到 ${parsedRows.length} 筆考勤資料。\n確定要直接寫入資料庫嗎？`)) return;

    const btn = document.getElementById('global_att_btn');
    const progressDiv = document.getElementById('global_att_progress');
    const statusText = document.getElementById('global_att_status');
    btn.disabled = true; btn.classList.add('opacity-50', 'cursor-not-allowed');
    textarea.disabled = true; progressDiv.classList.remove('hidden');

    let successCount = 0;
    for (let i = 0; i < parsedRows.length; i++) {
        const row = parsedRows[i];
        statusText.innerText = `${i + 1} / ${parsedRows.length}`;
        const fd = new FormData();
        fd.append('payroll_month', currentMonth);
        fd.append('nick_name', row.nick_name);
        fd.append('location', row.location);
        fd.append('work_date', row.work_date);
        fd.append('in_time', row.in_time);
        fd.append('out_time', row.out_time);
        fd.append('normal_hours', row.normal_hours);
        try {
            const resp = await fetch('/add_daily_attendance', { method: 'POST', body: fd });
            const result = await resp.json();
            if (result.status === 'success') successCount++;
        } catch (e) { console.error('上傳單筆考勤失敗', e); }
    }

    alert(`🎉 寫入完成！成功匯入 ${successCount} / ${parsedRows.length} 筆考勤資料。\n畫面將自動重新整理。`);
    window.location.reload();
}

async function executeGlobalSalesPaste() {
    const textarea = document.getElementById('global_sales_textarea');
    const pastedData = textarea.value;
    if (!pastedData.trim()) { alert('資料區不能為空，請貼上 Excel 資料。'); return; }

    const rows = pastedData.split('\n');
    const parsedRows = [];
    rows.forEach((row, index) => {
        if (!row.trim()) return;
        const cols = row.split('\t').map(c => c.trim());
        if (cols[0].toLowerCase().includes('shop')) return; // 自動跳過標題列

        if (cols.length >= 10) {
            const shop = cols[0] || '';
            const loc = cols[1] || '';
            const fullLocation = (shop + " " + loc).trim(); // 組合 Shop + Location
            
            let pastedDate = formatPasteDate(cols[4]);
            if (/^\d{1,2}$/.test(pastedDate)) {
                pastedDate = `${currentMonth}-${pastedDate.padStart(2, '0')}`;
            }

            let finalModel = cols[5];
            if (!finalModel || finalModel.toUpperCase() === '#N/A') {
                finalModel = cols[7];
            }

            parsedRows.push({
                promoter_name: cols[2], // 第 3 欄: Promoter
                location: fullLocation,
                date: pastedDate,
                model: finalModel,
                quantity: parseInt(cols[8] || 1),
                price: parseFloat(cols[9] || 0),
            });
        } else {
            console.warn(`第 ${index + 1} 行欄位不足，已略過:`, row);
        }
    });

    const validRows = parsedRows.filter(r => !isNaN(r.price) && r.price > 0 && r.model);
    if (validRows.length === 0) {
        alert('未能解析出有效的資料，請確認欄位與上方格式相符 (特別是型號與單價)。');
        return;
    }

    if (!confirm(`解析成功！共讀取到 ${validRows.length} 筆有效單據。\n確定要直接寫入資料庫嗎？`)) return;

    const btn = document.getElementById('global_sales_btn');
    const progressDiv = document.getElementById('global_sales_progress');
    const statusText = document.getElementById('global_sales_status');
    btn.disabled = true; btn.classList.add('opacity-50', 'cursor-not-allowed');
    textarea.disabled = true; progressDiv.classList.remove('hidden');

    let successCount = 0;
    for (let i = 0; i < validRows.length; i++) {
        const row = validRows[i];
        statusText.innerText = `${i + 1} / ${validRows.length}`;
        const fd = new FormData();
        fd.append('payroll_month', currentMonth);
        fd.append('promoter_name', row.promoter_name);
        fd.append('location', row.location);
        fd.append('date', row.date);
        fd.append('model', row.model);
        fd.append('quantity', row.quantity);
        fd.append('price', row.price);
        try {
            const resp = await fetch('/add_sales_record', { method: 'POST', body: fd });
            const result = await resp.json();
            if (result.status === 'success') successCount++;
        } catch (e) { console.error('上傳單筆銷售失敗', e); }
    }

    alert(`🎉 寫入完成！成功匯入 ${successCount} / ${validRows.length} 筆銷售單據。\n畫面將自動重新整理。`);
    window.location.reload();
}
