const pageDataElement = document.getElementById('index-page-data');
const pageData = pageDataElement ? JSON.parse(pageDataElement.textContent) : {};
const currentMonth = pageData.currentMonth || '';

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

function editAttendance(name, loc, days, hours, ot, exp, adj, bonus, monthly_hr, default_hr) {
    document.getElementById('att_name_display').innerText = name;
    document.getElementById('att_name_hidden').value = name;
    document.getElementById('att_loc_hidden').value = loc;

    const locDisplay = document.getElementById('att_loc_display');
    if (locDisplay) {
        locDisplay.innerText = loc;
    }

    const newLocInput = document.getElementById('new_loc');
    if (newLocInput) {
        newLocInput.value = loc;
    }

    setDateRange(document.getElementById('new_date'), currentMonth, true);
    document.getElementById('att_exp').value = exp || 0;
    document.getElementById('att_adj').value = adj || 0;
    document.getElementById('att_bonus').value = bonus || 0;

    const hrInput = document.getElementById('att_monthly_hr');
    hrInput.value = (monthly_hr !== null && monthly_hr !== undefined) ? monthly_hr : '';
    hrInput.placeholder = `預設 $${default_hr}`;

    const hrHint = document.getElementById('att_hr_hint');
    if (hrHint) {
        hrHint.innerHTML = `ℹ️ 該員工預設：$${default_hr}`;
    }

    document.getElementById('daily_records_body').innerHTML = '<tr><td colspan="9" class="text-center">載入中...</td></tr>';
    refreshDailyTable(name, loc);
    openModal('attendanceModal');
}

function updateInitAttDefaultHr() {
    const select = document.getElementById('init_att_promoter');
    const selectedOption = select.options[select.selectedIndex];
    const defaultHr = selectedOption.getAttribute('data-hr');
    const hintEl = document.getElementById('init_att_hr_hint');
    const inputEl = document.getElementById('init_att_monthly_hr');

    if (defaultHr) {
        hintEl.innerHTML = `ℹ️ 該員工預設時薪為 <strong>$${defaultHr}</strong>`;
        inputEl.placeholder = `預設 $${defaultHr}`;
    } else {
        hintEl.innerHTML = 'ℹ️ 請先選擇推廣員以檢視預設時薪';
        inputEl.placeholder = '若留空則使用系統預設時薪';
    }
}

function startNewAttendanceGroup() {
    const select = document.getElementById('init_att_promoter');
    const promoter = select.value;
    const location = document.getElementById('init_att_loc').value;
    const monthlyHr = document.getElementById('init_att_monthly_hr').value;

    if (!promoter || !location) {
        alert('請完整選擇推廣員與店鋪！');
        return;
    }

    const selectedOption = select.options[select.selectedIndex];
    const defaultHr = selectedOption ? parseFloat(selectedOption.getAttribute('data-hr')) : 0;
    closeModal(document.getElementById('newAttendanceGroupModal'));
    const hourlyRate = monthlyHr ? parseFloat(monthlyHr) : null;
    editAttendance(promoter, location, 0, 0, 0, 0, 0, 0, hourlyRate, defaultHr);
}

function refreshDailyTable(name, location) {
    fetch(`/api/daily_attendance/${currentMonth}/${encodeURIComponent(name)}/${encodeURIComponent(location)}`)
        .then(response => response.json())
        .then(data => {
            const tbody = document.getElementById('daily_records_body');
            tbody.innerHTML = '';

            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" class="text-slate-500 py-3 text-center text-sm">此地點尚無打卡明細。</td></tr>';
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
    const name = document.getElementById('att_name_display').innerText;
    const location = document.getElementById('att_loc_display').innerText;
    const dateInput = document.getElementById('new_date').value;
    const inInput = document.getElementById('new_in').value;
    const outInput = document.getElementById('new_out').value;
    const normalInput = document.getElementById('new_normal').value;

    if (!dateInput || !inInput || !outInput) {
        alert('請完整填寫日期與時間！');
        return;
    }

    const formData = new FormData();
    formData.append('payroll_month', currentMonth);
    formData.append('nick_name', name);
    formData.append('location', location);
    formData.append('work_date', dateInput);
    formData.append('in_time', inInput);
    formData.append('out_time', outInput);
    formData.append('normal_hours', normalInput || 8.0);

    fetch('/add_daily_attendance', { method: 'POST', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                refreshDailyTable(name, location);
                document.getElementById('new_in').value = '12:00';
                document.getElementById('new_out').value = '20:00';
                document.getElementById('new_normal').value = '8.0';
            }
        });
}

function openSalesModal(name, location, monthlyComm, defaultComm) {
    document.getElementById('sales_name_display').innerText = name;
    document.getElementById('sales_loc_display').innerText = location;

    const locSelect = document.getElementById('new_sales_loc');
    if (locSelect) {
        locSelect.value = location;
        locSelect.disabled = true;
    }

    const commInput = document.getElementById('sales_monthly_comm_input');
    commInput.value = (monthlyComm !== null && monthlyComm !== undefined) ? monthlyComm : '';
    commInput.placeholder = `預設 ${defaultComm}`;

    const hintEl = document.getElementById('sales_comm_hint');
    if (hintEl) {
        hintEl.innerHTML = `ℹ️ 該員工預設：${(defaultComm * 100).toFixed(0)}%`;
    }

    setDateRange(document.getElementById('new_sales_date'), currentMonth, true);
    document.getElementById('sales_records_body').innerHTML = '<tr><td colspan="7" class="py-4 text-center"><div class="animate-spin w-5 h-5 border-2 border-green-500 border-t-transparent rounded-full mx-auto mb-2"></div>正在撈取該店銷售紀錄...</td></tr>';
    openModal('salesModal');
    refreshSalesTable(name, location);
}

function saveSalesComm() {
    const name = document.getElementById('sales_name_display').innerText;
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

function updateInitSalesDefaultComm() {
    const select = document.getElementById('init_sales_promoter');
    const selectedOption = select.options[select.selectedIndex];
    const defaultComm = selectedOption.getAttribute('data-comm');
    const hintEl = document.getElementById('init_sales_comm_hint');
    const inputEl = document.getElementById('init_sales_monthly_comm');

    if (defaultComm) {
        const pct = (parseFloat(defaultComm) * 100).toFixed(0);
        hintEl.innerHTML = `ℹ️ 該員工預設佣金為 <strong>${pct}%</strong>`;
        inputEl.placeholder = `預設 ${defaultComm}`;
    } else {
        hintEl.innerHTML = 'ℹ️ 請先選擇推廣員，小數表示 (例: 3% 輸入 0.03)';
        inputEl.placeholder = '若留空則使用預設';
    }
}

function refreshSalesTable(name, location) {
    fetch(`/api/sales_records/${currentMonth}/${encodeURIComponent(name)}/${encodeURIComponent(location)}`)
        .then(response => response.json())
        .then(data => {
            const tbody = document.getElementById('sales_records_body');
            tbody.innerHTML = '';

            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-slate-500 py-3 text-center text-sm">此地點尚無銷售紀錄。</td></tr>';
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
    const name = document.getElementById('sales_name_display').innerText;
    const location = document.getElementById('sales_loc_display').innerText;

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
    const name = document.getElementById('sales_name_display').innerText;
    const location = document.getElementById('sales_loc_display').innerText;
    const dateInput = document.getElementById('new_sales_date').value;
    const modelInput = document.getElementById('new_sales_model').value;
    const qtyInput = document.getElementById('new_sales_qty').value;
    const priceInput = document.getElementById('new_sales_price').value;

    if (!modelInput || !priceInput) {
        alert('請完整填寫「型號」與「單價」！');
        return;
    }

    const formData = new FormData();
    formData.append('payroll_month', currentMonth);
    formData.append('promoter_name', name);
    formData.append('date', dateInput);
    formData.append('location', location);
    formData.append('model', modelInput);
    formData.append('quantity', qtyInput);
    formData.append('price', priceInput);

    fetch('/add_sales_record', { method: 'POST', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                document.getElementById('new_sales_model').value = '';
                document.getElementById('new_sales_qty').value = '1';
                document.getElementById('new_sales_price').value = '';
                refreshSalesTable(name, location);
            }
        });
}

function startNewSalesGroup() {
    const select = document.getElementById('init_sales_promoter');
    const promoter = select.value;
    const location = document.getElementById('init_sales_loc').value;
    const monthlyComm = document.getElementById('init_sales_monthly_comm').value;

    if (!promoter || !location) {
        alert('請完整選擇推廣員與店鋪！');
        return;
    }

    const selectedOption = select.options[select.selectedIndex];
    const defaultComm = selectedOption ? parseFloat(selectedOption.getAttribute('data-comm')) : 0.03;
    const commValue = monthlyComm ? parseFloat(monthlyComm) : null;
    closeModal(document.getElementById('newSalesGroupModal'));
    openSalesModal(promoter, location, commValue, defaultComm);
}

document.addEventListener('DOMContentLoaded', function() {
    // 已改用 Tailwind modal（手動 closeModal），不再依賴 Bootstrap hidden.bs.modal 事件
});
