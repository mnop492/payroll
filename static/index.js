const pageDataElement = document.getElementById('index-page-data');
const pageData = pageDataElement ? JSON.parse(pageDataElement.textContent) : {};
const currentMonth = pageData.currentMonth || '';

// ── 暫存陣列：批次寫入用 ──
let pendingAttendanceRows = [];
let pendingSalesRows = [];

// ── Helper：從下拉選單取得當前選取的員工與地點 ──
function getActiveAttName() { const el = document.getElementById('att_modal_promoter'); return el ? el.value : ''; }
function getActiveAttLoc() { const el = document.getElementById('att_modal_loc'); return el ? el.value : ''; }
function getActiveSalesName() { const el = document.getElementById('sales_modal_promoter'); return el ? el.value : ''; }
function getActiveSalesLoc() { const el = document.getElementById('sales_modal_loc'); return el ? el.value : ''; }

// ==========================================
// 考勤視窗邏輯
// ==========================================

function openNewAttendanceModal() {
    document.getElementById('att_modal_promoter').value = '';
    document.getElementById('att_modal_loc').value = '';
    document.getElementById('att_name_hidden').value = '';
    document.getElementById('att_loc_hidden').value = '';
    const nl = document.getElementById('new_loc');
    if (nl) nl.value = '';
    ['att_exp','att_adj','att_bonus','att_monthly_hr'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
    });
    const hint = document.getElementById('att_hr_hint');
    if (hint) hint.innerHTML = 'ℹ️ 請先選擇推廣員以檢視預設時薪';
    setDateRange(document.getElementById('new_date'), currentMonth, true);
    const tbody = document.getElementById('daily_records_body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-500 py-6">請完整選擇上方「推廣員」與「地點」以開始新增紀錄。</td></tr>';
    updateSaveAllButtons();
    openModal('attendanceModal');
}

function handleAttModalChange() {
    const name = getActiveAttName();
    const location = getActiveAttLoc();
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

    const tbody = document.getElementById('daily_records_body');
    if (name && location) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-400 py-6">載入中...</td></tr>';
        refreshDailyTable(name, location);
    } else if (tbody) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-500 py-6">請完整選擇上方「推廣員」與「地點」以載入資料。</td></tr>';
    }
    updateSaveAllButtons();
}

function editAttendance(name, loc, days, hours, ot, exp, adj, bonus, monthly_hr, default_hr) {
    document.getElementById('att_modal_promoter').value = name;
    document.getElementById('att_modal_loc').value = loc;
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
    const name = getActiveSalesName();
    const location = getActiveSalesLoc();
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
    // Clear daily records table body
    const tbody = document.getElementById('daily_records_body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-500 py-6">尚無紀錄。</td></tr>';
    // Clear adjustment form fields
    const fields = ['att_name_hidden', 'att_loc_hidden', 'att_monthly_hr', 'att_exp', 'att_bonus', 'att_adj'];
    fields.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const hrHint = document.getElementById('att_hr_hint');
    if (hrHint) hrHint.textContent = '';
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
            const tbody = document.getElementById('daily_records_body');
            tbody.innerHTML = '';

            if (data.length === 0) {
                tbody.innerHTML = '';
                renderPendingAttendanceRows(tbody, name, location);
                return;
            }

            data.forEach((record, index) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="text-center text-sm text-slate-500">${index + 1}</td>
                    <td class="text-center font-bold text-sm">${record.work_date}</td>
                    <td class="text-center"><span class="inline-flex items-center px-2 py-0.5 rounded-full text-sm font-medium bg-slate-700 text-slate-200">${record.location}</span></td>
                    <td>
                        <input type="hidden" name="record_id[]" value="${record.id}">
                        <input type="time" name="in_time[]" class="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1 text-sm text-slate-200 w-full" value="${record.in_time}">
                    </td>
                    <td>
                        <input type="time" name="out_time[]" class="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1 text-sm text-slate-200 w-full" value="${record.out_time}">
                    </td>
                    <td>
                        <input type="number" step="0.5" name="normal_hours[]" class="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1 text-sm text-slate-200 w-full" value="${parseFloat(record.normal_hours || 8.0).toFixed(1)}">
                    </td>
                    <td class="text-center font-bold text-sm">${parseFloat(record.actual_hours).toFixed(2)}</td>
                    <td class="text-center text-red-400 text-sm">${parseFloat(record.ot_hours).toFixed(2)}</td>
                    <td class="text-center">
                        <button type="button" class="border border-red-800/50 text-red-400 hover:bg-red-900/30 text-sm font-medium py-1 px-2 rounded-lg transition-colors" onclick="deleteRecord(${record.id}, '${name}', '${location}')">🗑️</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
            // Append pending rows (not yet saved to DB)
            renderPendingAttendanceRows(tbody, name, location);
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

function addNewRecordFromUI() {
    const name = getActiveAttName();
    const location = getActiveAttLoc();
    const dateInput = document.getElementById('new_date').value;
    const inInput = document.getElementById('new_in').value;
    const outInput = document.getElementById('new_out').value;
    const normalInput = document.getElementById('new_normal').value;

    if (!dateInput || !inInput || !outInput) {
        alert('請完整填寫日期與時間！');
        return;
    }

    pendingAttendanceRows.push({
        nick_name: name,
        work_date: dateInput,
        location: location,
        in_time: inInput,
        out_time: outInput,
        normal_hours: parseFloat(normalInput || 8.0),
    });

    // Reset input fields
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
        tr.className = 'bg-amber-900/20';
        tr.innerHTML = `
            <td class="text-center text-sm text-amber-400">⏳</td>
            <td class="text-center font-bold text-sm text-amber-200">${row.work_date}</td>
            <td class="text-center"><span class="inline-flex items-center px-2 py-0.5 rounded-full text-sm font-medium bg-amber-900/50 text-amber-200">${row.location}</span></td>
            <td class="text-center text-sm text-amber-200">${row.in_time}</td>
            <td class="text-center text-sm text-amber-200">${row.out_time}</td>
            <td class="text-center text-sm text-amber-200">${row.normal_hours.toFixed(1)}</td>
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
                if (cols.length >= 4) {
                    pendingAttendanceRows.push({
                        nick_name: name,
                        work_date: cols[0],
                        location: cols[1] || location,
                        in_time: cols[2],
                        out_time: cols[3],
                        normal_hours: parseFloat(cols[4] || 8.0),
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
                if (cols.length >= 3) {
                    pendingSalesRows.push({
                        promoter_name: name,
                        date: cols[0],
                        location: cols[1] || location,
                        model: cols[2],
                        quantity: parseInt(cols[3] || 1),
                        price: parseFloat(cols[4] || 0),
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
        if (cols.length >= 4) {
            pendingAttendanceRows.push({
                nick_name: name,
                work_date: cols[0],
                location: cols[1] || location,
                in_time: cols[2],
                out_time: cols[3],
                normal_hours: parseFloat(cols[4] || 8.0),
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
        alert('⚠️ 無法解析資料，請檢查貼上的格式是否符合對照表要求（至少 4 欄）。');
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
        if (cols.length >= 3) {
            pendingSalesRows.push({
                promoter_name: name,
                date: cols[0],
                location: cols[1] || location,
                model: cols[2],
                quantity: parseInt(cols[3] || 1),
                price: parseFloat(cols[4] || 0),
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
        alert('⚠️ 無法解析資料，請檢查貼上的格式是否符合對照表要求（至少 3 欄）。');
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
        if (cols.length >= 5) {
            parsedRows.push({
                nick_name: cols[0],
                location: cols[1],
                work_date: cols[2],
                in_time: cols[3],
                out_time: cols[4],
                normal_hours: parseFloat(cols[5] || 8.0),
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
        if (cols.length >= 5) {
            parsedRows.push({
                promoter_name: cols[0],
                location: cols[1],
                date: cols[2],
                model: cols[3],
                quantity: parseInt(cols[4] || 1),
                price: parseFloat(cols[5] || 0),
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
