import os
from werkzeug.utils import secure_filename
import sqlite3
import logging
import json
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, send_file, jsonify, session
import pandas as pd
import io
import csv
from datetime import datetime
from payroll_engine import process_payroll_from_db
from importer import process_excel_import

app = Flask(__name__)
app.secret_key = "super_secret_key"

# 管理員稽核訪問設定
ADMIN_USERS = {'admin', 'auditor', 'superuser'}
AUDIT_ADMIN_PASSWORD = os.environ.get('AUDIT_ADMIN_PASSWORD', 'audit2026')

def is_audit_admin():
    return bool(session.get('is_admin')) or session.get('user') in ADMIN_USERS

# 確保 history 資料夾存在
HISTORY_FOLDER = 'history'
os.makedirs(HISTORY_FOLDER, exist_ok=True)

# 🌟 1. 統一管理上傳資料夾名稱
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

LOG_FOLDER = 'logs'
os.makedirs(LOG_FOLDER, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_FOLDER, 'system.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_db_connection():
    conn = sqlite3.connect('payroll.db')
    conn.row_factory = sqlite3.Row
    return conn


# --- Audit log helpers ---------------------------------
def ensure_audit_table():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS AuditLog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user TEXT,
            action TEXT NOT NULL,
            table_name TEXT,
            record_id TEXT,
            old_value TEXT,
            new_value TEXT,
            ip TEXT
        )
    ''')
    conn.commit()
    conn.close()


def log_audit(action, table_name, record_id=None, old_value=None, new_value=None, user=None, ip=None):
    """Insert an audit entry into AuditLog."""
    try:
        ts = datetime.utcnow().isoformat()
        # if user not provided, try to pick from session or headers
        if not user:
            try:
                user = session.get('user')
            except Exception:
                user = None
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO AuditLog (timestamp, user, action, table_name, record_id, old_value, new_value, ip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ts, user, action, table_name, str(record_id) if record_id is not None else None,
              json.dumps(old_value, ensure_ascii=False) if old_value is not None else None,
              json.dumps(new_value, ensure_ascii=False) if new_value is not None else None,
              ip))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.exception('Failed to write audit log: %s', e)


def ensure_monthly_rates_table():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS MonthlyRates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payroll_month TEXT NOT NULL,
            nick_name TEXT NOT NULL,
            hourly_rate REAL,
            allowance REAL,
            commission_rate REAL,
            UNIQUE(payroll_month, nick_name)
        )
    ''')
    conn.commit()
    conn.close()

# ensure tables exist at startup
ensure_audit_table()
ensure_monthly_rates_table()

# 🌟 全新：自動彙總並同步考勤總表的函數
def sync_attendance_summary(month, nick_name, location):
    conn = get_db_connection()
    
    # 1. 計算該員工在該店鋪的最新的「總日數、總工時、總OT」
    # (工時計算邏輯與 Excel 匯入一致：實際工時減去 OT)
    summary = conn.execute('''
        SELECT 
            COUNT(work_date) as t_days,
            SUM(actual_hours - ot_hours) as t_hours,
            SUM(ot_hours) as t_ot
        FROM DailyAttendance 
        WHERE payroll_month = ? AND nick_name = ? AND location = ?
    ''', (month, nick_name, location)).fetchone()
    
    days = summary['t_days'] or 0
    hours = summary['t_hours'] or 0.0
    ot = summary['t_ot'] or 0.0
    
    # 2. 確保 Attendance 總表中有這筆紀錄 (避免因為是新加的而找不到)
    conn.execute('''
        INSERT OR IGNORE INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours)
        VALUES (?, ?, ?, 0, 0, 0)
    ''', (month, nick_name, location))
    
    # 3. 把算出來的最新總計，覆寫回 Attendance 總表
    conn.execute('''
        UPDATE Attendance 
        SET days_worked = ?, hours = ?, ot_hours = ?
        WHERE payroll_month = ? AND nick_name = ? AND location = ?
    ''', (days, hours, ot, month, nick_name, location))
    
    conn.commit()
    conn.close()
    
@app.route('/')
def index():
    current_month = request.args.get('month', pd.Timestamp.now().strftime('%Y-%m'))
    conn = get_db_connection()
    
    # 1. 讀取銷售與考勤紀錄
    records = conn.execute("SELECT * FROM Sales WHERE payroll_month = ?", (current_month,)).fetchall()
    attendances_raw = conn.execute("SELECT * FROM Attendance WHERE payroll_month = ?", (current_month,)).fetchall()
    
    # 處理 None 值避免 HTML 報錯
    attendances = []
    for row in attendances_raw:
        d = dict(row)
        fields_to_fix = ['hours', 'days_worked', 'ot_hours', 'expenses', 'adjustment', 'attendance_bonus']
        for field in fields_to_fix:
            if d.get(field) is None: d[field] = 0
        if d.get('basic_pay_override') is None: d['basic_pay_override'] = ''
        if d.get('allowance_override') is None: d['allowance_override'] = ''
        attendances.append(d)
        
    # 2. 銷售彙總計算
    staff_summary_raw = conn.execute('''
        SELECT promoter_name as name, location as main_location, 
               COUNT(*) as total_entries, SUM(quantity * price) as total_amount 
        FROM Sales WHERE payroll_month = ? 
        GROUP BY promoter_name, location ORDER BY name, total_amount DESC
    ''', (current_month,)).fetchall()

    payroll_results = process_payroll_from_db(current_month)
    commission_map = {(row['員工'], row['地點']): float(row['總佣金']) for row in payroll_results}

    staff_summary = []
    for row in staff_summary_raw:
        d = dict(row)
        d['total_amount'] = float(d['total_amount'] or 0)
        d['total_comm'] = commission_map.get((d['name'], d['main_location']), 0.0)
        staff_summary.append(d)

    # 3. 讀取其他主檔資料
    locations = conn.execute("SELECT name FROM Locations ORDER BY name").fetchall()
    products = conn.execute("SELECT model FROM Products ORDER BY model").fetchall()
    
    # ✅ 確保同時撈取 hourly_rate 與 commission_rate
    employees_rows = conn.execute("SELECT nick_name, full_name, hourly_rate, commission_rate FROM Employees ORDER BY nick_name").fetchall()
    monthly_rates_rows = conn.execute("SELECT nick_name, hourly_rate, commission_rate FROM MonthlyRates WHERE payroll_month = ?", (current_month,)).fetchall()
    
    employees = employees_rows
    
    # 4. 建立對照字典 (包含時薪與佣金)
    monthly_rate_map = {r['nick_name']: float(r['hourly_rate']) if r['hourly_rate'] is not None else None for r in monthly_rates_rows}
    monthly_comm_map = {r['nick_name']: float(r['commission_rate']) if r['commission_rate'] is not None else None for r in monthly_rates_rows}
    
    emp_full_map = {r['nick_name']: (r['full_name'] or '') for r in employees_rows}
    emp_default_hr_map = {r['nick_name']: float(r['hourly_rate'] or 0) for r in employees_rows}
    emp_default_comm_map = {r['nick_name']: float(r['commission_rate'] or 0.03) for r in employees_rows}

    conn.close()

    # 🌟 關鍵修復 1：確保「考勤紀錄」有被正確塞入時薪與全名
    for a in attendances:
        a['full_name'] = emp_full_map.get(a.get('nick_name'), '')
        a['monthly_hourly_rate'] = monthly_rate_map.get(a.get('nick_name'))
        a['default_hourly_rate'] = emp_default_hr_map.get(a.get('nick_name'), 0)

    # 🌟 關鍵修復 2：確保「銷售彙總」有被正確塞入佣金與全名
    for s in staff_summary:
        s['full_name'] = emp_full_map.get(s.get('name'), '')
        s['monthly_hourly_rate'] = monthly_rate_map.get(s.get('name'))
        s['monthly_comm'] = monthly_comm_map.get(s.get('name'))
        s['default_comm'] = emp_default_comm_map.get(s.get('name'), 0.03)

    return render_template('index.html', current_month=current_month, staff_summary=staff_summary, 
                           records=records, attendances=attendances, locations=locations, 
                           products=products, employees=employees)

# 🌟 API：從銷售介面快速更新月度佣金
@app.route('/update_monthly_comm_api', methods=['POST'])
def update_monthly_comm_api():
    month = request.form.get('month')
    name = request.form.get('promoter')
    comm_val = request.form.get('monthly_comm', '').strip()
    
    conn = get_db_connection()
    if comm_val == '':
        # 若清空，則將該月佣金欄位設為 NULL (不刪除整列，因為可能還有時薪資料)
        conn.execute('UPDATE MonthlyRates SET commission_rate = NULL WHERE payroll_month = ? AND nick_name = ?', (month, name))
    else:
        # 新增或更新
        conn.execute('''
            INSERT INTO MonthlyRates (payroll_month, nick_name, commission_rate)
            VALUES (?, ?, ?)
            ON CONFLICT(payroll_month, nick_name) DO UPDATE SET commission_rate = excluded.commission_rate
        ''', (month, name, float(comm_val)))
    
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})
    
@app.route('/delete_attendance/<int:id>', methods=['POST'])
def delete_attendance(id):
    conn = get_db_connection()
    
    # 🌟 第一步：先找出這筆總表紀錄是誰、在哪、哪個月？
    # 這樣我們才知道要連帶刪除哪些 DailyAttendance
    target = conn.execute('''
        SELECT payroll_month, nick_name, location 
        FROM Attendance 
        WHERE id = ?
    ''', (id,)).fetchone()
    
    if target:
        month = target['payroll_month']
        name = target['nick_name']
        loc = target['location']
        
        # 🌟 第二步：先清理「每日明細」 (子表)
        conn.execute('''
            DELETE FROM DailyAttendance 
            WHERE payroll_month = ? AND nick_name = ? AND location = ?
        ''', (month, name, loc))
        
        # 🌟 第三步：再刪除「總結算紀錄」 (主表)
        conn.execute("DELETE FROM Attendance WHERE id = ?", (id,))
        
        conn.commit()
        flash(f"✅ 已徹底刪除 {name} 在 {loc} 的考勤總表及所有每日明細", "success")
    else:
        flash("❌ 找不到該筆紀錄", "danger")
        
    conn.close()
    return redirect(request.referrer or url_for('index'))

@app.route('/insert_record', methods=['POST'])
def insert_record():
    payroll_month = request.form.get('payroll_month')
    date = request.form.get('date')
    promoter = request.form.get('promoter')
    location = request.form.get('location')
    model = request.form.get('model')
    quantity = request.form.get('quantity')
    price = request.form.get('price')

    conn = get_db_connection()
    cur = conn.execute('''
        INSERT INTO Sales (payroll_month, date, promoter_name, location, model, quantity, price)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (payroll_month, date, promoter, location, model, quantity, price))
    conn.commit()
    new_id = cur.lastrowid
    # audit
    try:
        log_audit('create', 'Sales', record_id=new_id, new_value={'payroll_month': payroll_month, 'date': date, 'promoter_name': promoter, 'location': location, 'model': model, 'quantity': quantity, 'price': price}, user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()

    logging.info(f"成功寫入單據 - 月份: {payroll_month}, 員工: {promoter}")
    flash(f'成功新增一筆 {promoter} 的紀錄 ({payroll_month})！', 'success')
    return redirect(url_for('index'))

# 🌟 修復 1：計算薪資路由 (適應單一回傳值)
import pandas as pd
import os
from flask import render_template, request, flash, redirect, url_for, send_from_directory

@app.route('/calculate_payroll', methods=['POST'])
def calculate_payroll():
    calc_month = request.form.get('calc_month')
    
    # 1. 取得計算結果
    records = process_payroll_from_db(calc_month)
    
    if records:
        # 2. 解決 Total 消失問題：手動計算總和 (對應你 UI 裡的 totals 變數)
        totals = {
            'basic': sum(r.get('底薪', 0) for r in records),
            'comm': sum(r.get('總佣金', 0) for r in records),
            'net': sum(r.get('實發薪資', 0) for r in records)
        }
        
        # 3. 解決 Not Found 問題：定義 excel_file 變數並產生檔案
        excel_file = f"Payroll_Summary_{calc_month}.xlsx"
        
        # 確保 outputs 資料夾存在並儲存檔案
        df = pd.DataFrame(records)
        output_dir = 'outputs'
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        df.to_excel(os.path.join(output_dir, excel_file), index=False)
        
        flash(f'{calc_month} 月份計算成功！', 'success')
        
        # 4. 關鍵：將所有變數傳回 template，這會讓你的 UI 恢復正常
        return render_template('result.html', 
                               records=records, 
                               calc_month=calc_month, 
                               excel_file=excel_file, # 補回這個變數
                               totals=totals)         # 補回這個變數
    else:
        flash(f'找不到 {calc_month} 的數據，請確認已輸入資料。', 'danger')
        return redirect(url_for('index'))

@app.route('/delete_record/<int:record_id>', methods=['POST'])
def delete_record(record_id):
    conn = get_db_connection()
    old = conn.execute('SELECT * FROM Sales WHERE id = ?', (record_id,)).fetchone()
    old_dict = dict(old) if old else None
    conn.execute('DELETE FROM Sales WHERE id = ?', (record_id,))
    conn.commit()
    conn.close()
    try:
        log_audit('delete', 'Sales', record_id=record_id, old_value=old_dict, user=None, ip=request.remote_addr)
    except Exception:
        pass

    logging.info(f"已刪除銷售紀錄 ID: {record_id}")
    flash(f'紀錄 (ID: {record_id}) 已成功刪除！', 'warning')
    return redirect(url_for('index'))

# 🌟 修復 2：查看糧單路由
@app.route('/view_payslip/<int:idx>/<month>')
def view_payslip(idx, month):
    records = process_payroll_from_db(month)
    
    if records and idx < len(records):
        target_emp = records[idx]
        return render_template('payslip.html', emp=target_emp, month=month)
    
    flash("找不到該薪資紀錄", "danger")
    return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join('outputs', filename)
    return send_file(filepath, as_attachment=True)

@app.route('/insert_attendance', methods=['POST'])
def insert_attendance():
    payroll_month = request.form.get('payroll_month')
    nick_name = request.form.get('nick_name').strip()
    location = request.form.get('location').strip()
    
    # 🌟 修復 3：確保從表單拿到的數字是真正的數值型態，避免存入字串
    days = int(request.form.get('days_worked', 0) or 0)
    hours = float(request.form.get('hours', 0) or 0)
    ot_hours = float(request.form.get('ot_hours', 0) or 0)
    expenses = float(request.form.get('expenses', 0) or 0)
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours, expenses)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(payroll_month, nick_name, location) DO UPDATE SET
        days_worked=excluded.days_worked, hours=excluded.hours, ot_hours=excluded.ot_hours, expenses=excluded.expenses
    ''', (payroll_month, nick_name, location, days, hours, ot_hours, expenses))
    conn.commit()
    conn.close()
    flash("考勤紀錄新增成功", "success")
    return redirect(url_for('index'))

# 🌟 修復 4：列印所有糧單
@app.route('/print_all/<calc_month>')
def print_all_payslips(calc_month):
    records = process_payroll_from_db(calc_month)
    
    if not records:
        flash(f'找不到 {calc_month} 的薪資資料，請先計算！', 'danger')
        return redirect(url_for('index'))
        
    return render_template('print_all.html', records=records, month=calc_month)

@app.route('/validate')
def validate_data():
    results = perform_validation()
    return render_template('validation.html', results=results)

@app.route('/download_validation')
def download_validation():
    results = perform_validation()
    df = pd.DataFrame(results)
    
    df.columns = ['月份', '員工', '地點', 'Excel底薪', '系統底薪', 'Excel佣金', '系統佣金', 
                  'Excel津貼', '系統津貼', 'Excel_MPF', '系統_MPF', 'Excel實發', '系統實發', '差異', '狀態']
    
    output_path = 'outputs/Validation_Report.xlsx'
    os.makedirs('outputs', exist_ok=True)
    df.to_excel(output_path, index=False)
    return send_from_directory('outputs', 'Validation_Report.xlsx', as_attachment=True)

def perform_validation():
    import os
    validation_results = []
    
    if not os.path.exists(HISTORY_FOLDER): return []

    for filename in sorted(os.listdir(HISTORY_FOLDER)):
        if filename.endswith('.xlsx') and not filename.startswith('~'):
            month_str = filename[:6]
            payroll_month = f"{month_str[:4]}-{month_str[4:]}"
            
            # 🌟 修復 5：正確接收單一變數
            sys_records = process_payroll_from_db(payroll_month)
            if not sys_records: continue
            
            try:
                filepath = os.path.join(HISTORY_FOLDER, filename)
                ex_df = pd.read_excel(filepath, sheet_name='Total', header=6)
                ex_df.columns = ex_df.columns.astype(str).str.strip()
                ex_df = ex_df.dropna(subset=['Name', 'Total'])
            except: continue

            for _, ex_row in ex_df.iterrows():
                name = str(ex_row['Name']).strip()
                loc = str(ex_row.get('Shop', '')).strip()
                
                ex_vals = {
                    'basic': round(float(ex_row.get('酬  金', 0)), 0),
                    'comm': round(float(ex_row.get('Basic Comm', 0)), 0),
                    'allow': round(float(ex_row.get('Allowance', 0)), 0),
                    'mpf': round(float(ex_row.get('MPF', 0)), 0),
                    'net': round(float(ex_row['Total']), 0)
                }

                sys = next((r for r in sys_records if r['員工'] == name and r['地點'] == loc), None)
                
                res = {
                    'month': payroll_month, 'name': name, 'location': loc,
                    'ex_basic': ex_vals['basic'], 'sys_basic': 0,
                    'ex_comm': ex_vals['comm'], 'sys_comm': 0,
                    'ex_allow': ex_vals['allow'], 'sys_allow': 0,
                    'ex_mpf': ex_vals['mpf'], 'sys_mpf': 0,
                    'ex_net': ex_vals['net'], 'sys_net': 0,
                    'diff': 0, 'status': "❓ 系統找不到"
                }

                if sys:
                    res.update({
                        'sys_basic': round(sys['底薪'], 0),
                        'sys_comm': round(sys['總佣金'], 0),
                        'sys_allow': round(sys['津貼'], 0),
                        'sys_mpf': round(sys['MPF扣除'], 0),
                        'sys_net': round(sys['實發薪資'], 0),
                    })
                    res['diff'] = res['sys_net'] - res['ex_net']
                    res['status'] = "✅ 匹配" if abs(res['diff']) <= 1 else "❌ 不匹配"

                validation_results.append(res)
    return validation_results

@app.route('/settings')
def settings():
    current_month = request.args.get('month', pd.Timestamp.now().strftime('%Y-%m'))
    conn = get_db_connection()
    employees = conn.execute("SELECT * FROM Employees ORDER BY nick_name").fetchall()
    
    # ✅ 修改：把 commission_rate 也撈出來
    monthly_rates = conn.execute("SELECT nick_name, hourly_rate, commission_rate FROM MonthlyRates WHERE payroll_month = ?", (current_month,)).fetchall()
    
    monthly_map = {r['nick_name']: r['hourly_rate'] for r in monthly_rates}
    monthly_comm_map = {r['nick_name']: r['commission_rate'] for r in monthly_rates} # ✅ 新增字典
    conn.close()
    
    # ✅ 修改：把 monthly_comm_map 傳給前端
    return render_template('settings.html', employees=employees, current_month=current_month, 
                           monthly_map=monthly_map, monthly_comm_map=monthly_comm_map)
@app.route('/update_monthly_rate', methods=['POST'])
def update_monthly_rate():
    payroll_month = request.form.get('payroll_month') or pd.Timestamp.now().strftime('%Y-%m')
    nick_name = request.form.get('nick_name')
    monthly_rate_value = request.form.get('monthly_hourly_rate', '').strip()

    conn = get_db_connection()
    old = conn.execute('SELECT * FROM MonthlyRates WHERE payroll_month = ? AND nick_name = ?', (payroll_month, nick_name)).fetchone()
    old_dict = dict(old) if old else None

    if monthly_rate_value == '':
        if old:
            conn.execute('DELETE FROM MonthlyRates WHERE payroll_month = ? AND nick_name = ?', (payroll_month, nick_name))
            conn.commit()
            try:
                log_audit('delete', 'MonthlyRates', record_id=f"{payroll_month}:{nick_name}", old_value=old_dict, user=None, ip=request.remote_addr)
            except Exception:
                pass
            flash(f"✅ 已移除 {nick_name} 的 {payroll_month} 月度時薪覆寫，改回預設時薪。", 'success')
        else:
            flash(f"⚠️ {nick_name} 在 {payroll_month} 沒有設定可移除。", 'warning')
    else:
        hourly_rate = float(monthly_rate_value)
        if old:
            conn.execute('''
                UPDATE MonthlyRates SET hourly_rate = ? WHERE payroll_month = ? AND nick_name = ?
            ''', (hourly_rate, payroll_month, nick_name))
            action = 'update'
        else:
            conn.execute('''
                INSERT INTO MonthlyRates (payroll_month, nick_name, hourly_rate) VALUES (?, ?, ?)
            ''', (payroll_month, nick_name, hourly_rate))
            action = 'create'
        conn.commit()
        new = conn.execute('SELECT * FROM MonthlyRates WHERE payroll_month = ? AND nick_name = ?', (payroll_month, nick_name)).fetchone()
        try:
            log_audit(action, 'MonthlyRates', record_id=f"{payroll_month}:{nick_name}", old_value=old_dict, new_value=dict(new) if new else None, user=None, ip=request.remote_addr)
        except Exception:
            pass
        flash(f"✅ 已儲存 {nick_name} 的 {payroll_month} 月度時薪：${hourly_rate:.2f}", 'success')

    conn.close()
    return redirect(url_for('settings', month=payroll_month))

@app.route('/update_employee', methods=['POST'])
def update_employee():
    emp_id = request.form.get('id')
    # 🌟 核心修復：接收全名
    full_name = request.form.get('full_name') 
    
    hourly_rate = float(request.form.get('hourly_rate', 0))
    allowance = float(request.form.get('allowance', 0))
    commission_rate = float(request.form.get('commission_rate', 0.03))
    mpf_start_month = request.form.get('mpf_start_month')
    payroll_month = request.form.get('payroll_month') or pd.Timestamp.now().strftime('%Y-%m')
    monthly_hourly_rate = request.form.get('monthly_hourly_rate', '').strip()
    monthly_commission_rate = request.form.get('monthly_commission_rate', '').strip() # ✅ 新增這行

    if emp_id:
        conn = get_db_connection()
        try:
            # capture old
            old = conn.execute('SELECT * FROM Employees WHERE id = ?', (emp_id,)).fetchone()
            old_dict = dict(old) if old else None
            nick_name = old['nick_name'] if old else None

            # 🌟 修正 SQL 語句：加入 full_name = ?
            conn.execute('''
                UPDATE Employees 
                SET full_name = ?, hourly_rate = ?, allowance = ?, commission_rate = ?, mpf_start_month = ?
                WHERE id = ?
            ''', (full_name, hourly_rate, allowance, commission_rate, mpf_start_month, emp_id))
            conn.commit()

            # ✅ 修改：同時處理 月度時薪 與 月度佣金
            if nick_name:
                # 如果兩個都留白，代表完全沒有覆寫，刪除該月紀錄
                if monthly_hourly_rate == '' and monthly_commission_rate == '':
                    conn.execute('DELETE FROM MonthlyRates WHERE payroll_month = ? AND nick_name = ?', (payroll_month, nick_name))
                else:
                    # 允許其中一個有值、另一個為空 (空值會存成 NULL)
                    hr_val = float(monthly_hourly_rate) if monthly_hourly_rate != '' else None
                    comm_val = float(monthly_commission_rate) if monthly_commission_rate != '' else None
                    
                    conn.execute('''
                        INSERT INTO MonthlyRates (payroll_month, nick_name, hourly_rate, commission_rate)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(payroll_month, nick_name) DO UPDATE SET 
                        hourly_rate = excluded.hourly_rate,
                        commission_rate = excluded.commission_rate
                    ''', (payroll_month, nick_name, hr_val, comm_val))
                
                conn.commit()

            # capture new and audit
            new = conn.execute('SELECT * FROM Employees WHERE id = ?', (emp_id,)).fetchone()
            new_dict = dict(new) if new else None
            try:
                log_audit('update', 'Employees', record_id=emp_id, old_value=old_dict, new_value=new_dict, user=None, ip=request.remote_addr)
            except Exception:
                pass

            flash("✅ 員工主檔資料已成功更新", "success")
        except Exception as e:
            flash(f"⚠️ 更新失敗：{str(e)}", "danger")
        finally:
            conn.close()
            
    return redirect(url_for('settings', month=payroll_month)) # ✅ 把 payroll_month 帶回去

@app.route('/save_special_comm', methods=['POST'])
def save_special_comm():
    model = request.form.get('model').strip()
    start = request.form.get('start')
    end = request.form.get('end')
    rate = request.form.get('rate')
    
    conn = get_db_connection()
    cur = conn.execute("INSERT INTO SpecialCommissions (model, start_month, end_month, rate) VALUES (?, ?, ?, ?)",
                 (model, start, end, float(rate)))
    conn.commit()
    new_id = cur.lastrowid
    try:
        log_audit('create', 'SpecialCommissions', record_id=new_id, new_value={'model': model, 'start_month': start, 'end_month': end, 'rate': float(rate)}, user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()
    flash(f"已成功加入 {model} 的特殊佣金規則", "success")
    return redirect(url_for('settings'))

@app.route('/delete_special_comm/<int:id>')
def delete_special_comm(id):
    conn = get_db_connection()
    old = conn.execute('SELECT * FROM SpecialCommissions WHERE id = ?', (id,)).fetchone()
    old_dict = dict(old) if old else None
    conn.execute("DELETE FROM SpecialCommissions WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    try:
        log_audit('delete', 'SpecialCommissions', record_id=id, old_value=old_dict, user=None, ip=request.remote_addr)
    except Exception:
        pass
    return redirect(request.referrer or url_for('manage_products'))

@app.route('/update_emp_mpf', methods=['POST'])
def update_emp_mpf():
    name = request.form.get('name')
    start_month = request.form.get('start_month')
    
    conn = get_db_connection()
    # capture old
    old = conn.execute('SELECT * FROM Employees WHERE nick_name = ?', (name,)).fetchone()
    old_dict = dict(old) if old else None
    conn.execute("UPDATE Employees SET mpf_start_month = ? WHERE nick_name = ?", (start_month, name))
    conn.commit()
    # capture new
    new = conn.execute('SELECT * FROM Employees WHERE nick_name = ?', (name,)).fetchone()
    new_dict = dict(new) if new else None
    try:
        log_audit('update', 'Employees', record_id=new_dict.get('id') if new_dict else None, old_value=old_dict, new_value=new_dict, user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()
    flash(f"已更新 {name} 的 MPF 起扣月份", "success")
    return redirect(url_for('settings'))

@app.route('/manage_products')
def manage_products():
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM Products ORDER BY model").fetchall()
    special_rules = conn.execute("SELECT * FROM SpecialCommissions ORDER BY start_month DESC").fetchall()
    conn.close()
    return render_template('manage_products.html', products=products, special_rules=special_rules)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('user')
        password = request.form.get('password')
        if user:
            session['user'] = user
            session['is_admin'] = False
            if user in ADMIN_USERS or (password and password == AUDIT_ADMIN_PASSWORD):
                session['is_admin'] = True
            flash(f'歡迎，{user}', 'success')
            return redirect(request.args.get('next') or url_for('index'))
        flash('請輸入使用者名稱', 'warning')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('is_admin', None)
    flash('已登出', 'info')
    return redirect(url_for('index'))

@app.route('/update_product_config', methods=['POST'])
def update_product_config():
    model = request.form.get('model')
    update_type = request.form.get('update_type') 
    rate = float(request.form.get('rate'))
    
    conn = get_db_connection()
    if update_type == 'permanent':
        # capture old
        old = conn.execute('SELECT * FROM Products WHERE model = ?', (model,)).fetchone()
        old_dict = dict(old) if old else None
        conn.execute("UPDATE Products SET commission_rate = ? WHERE model = ?", (rate, model))
        conn.commit()
        new = conn.execute('SELECT * FROM Products WHERE model = ?', (model,)).fetchone()
        new_dict = dict(new) if new else None
        try:
            log_audit('update', 'Products', record_id=new_dict.get('id') if new_dict else None, old_value=old_dict, new_value=new_dict, user=None, ip=request.remote_addr)
        except Exception:
            pass

        flash(f"✅ 已更新 {model} 的永久佣金比例為 {rate*100}%", "success")
    else:
        start = request.form.get('start_month')
        end = request.form.get('end_month')
        if not start or not end:
            flash("❌ 設定特佣時必須填寫開始與結束月份", "danger")
            return redirect(url_for('manage_products'))
        
        cur = conn.execute("INSERT INTO SpecialCommissions (model, start_month, end_month, rate) VALUES (?, ?, ?, ?)",
                     (model, start, end, rate))
        conn.commit()
        new_id = cur.lastrowid
        try:
            log_audit('create', 'SpecialCommissions', record_id=new_id, new_value={'model': model, 'start_month': start, 'end_month': end, 'rate': rate}, user=None, ip=request.remote_addr)
        except Exception:
            pass
        flash(f"✅ 已成功為 {model} 加入特佣規則 ({start} 至 {end})", "success")
    
    conn.close()
    return redirect(url_for('manage_products'))


@app.route('/audit_logs')
def audit_logs():
    if not is_audit_admin():
        flash('需要管理員權限才能查看稽核紀錄', 'warning')
        return redirect(url_for('login', next=request.path))
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    table = request.args.get('table')
    action = request.args.get('action')
    user_q = request.args.get('user')
    q = request.args.get('q')

    where = []
    params = []
    if table:
        where.append('table_name = ?')
        params.append(table)
    if action:
        where.append('action = ?')
        params.append(action)
    if user_q:
        where.append('user = ?')
        params.append(user_q)
    if q:
        where.append('(record_id = ? OR timestamp LIKE ? OR old_value LIKE ? OR new_value LIKE ?)')
        params.extend([q, f"%{q}%", f"%{q}%", f"%{q}%"])

    where_sql = ' AND '.join(where)
    if where_sql:
        where_sql = 'WHERE ' + where_sql

    conn = get_db_connection()
    total = conn.execute(f"SELECT COUNT(*) as c FROM AuditLog {where_sql}", params).fetchone()['c']
    offset = (page - 1) * per_page
    rows = conn.execute(f"SELECT * FROM AuditLog {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", params + [per_page, offset]).fetchall()
    tables = [row['table_name'] for row in conn.execute('SELECT DISTINCT table_name FROM AuditLog ORDER BY table_name').fetchall()]
    actions = [row['action'] for row in conn.execute('SELECT DISTINCT action FROM AuditLog ORDER BY action').fetchall()]
    users = [row['user'] for row in conn.execute('SELECT DISTINCT user FROM AuditLog ORDER BY user').fetchall() if row['user']]
    conn.close()

    entries = []
    for r in rows:
        d = dict(r)
        # pretty-print JSON fields for template
        try:
            d['old_value_pretty'] = json.dumps(json.loads(d['old_value']) if d.get('old_value') else None, ensure_ascii=False, indent=2)
        except Exception:
            d['old_value_pretty'] = d.get('old_value')
        try:
            d['new_value_pretty'] = json.dumps(json.loads(d['new_value']) if d.get('new_value') else None, ensure_ascii=False, indent=2)
        except Exception:
            d['new_value_pretty'] = d.get('new_value')
        entries.append(d)

    return render_template('audit_logs.html', entries=entries, page=page, per_page=per_page, total=total, table=table, action=action, user=user_q, q=q, tables=tables, actions=actions, users=users)


@app.route('/audit_logs/export')
def audit_logs_export():
    # Require a logged-in audit admin to export audit logs
    if not is_audit_admin():
        flash('需要管理員權限才能匯出稽核紀錄', 'warning')
        return redirect(url_for('login', next=request.path))

    table = request.args.get('table')
    action = request.args.get('action')
    user_q = request.args.get('user')
    q = request.args.get('q')
    ids = request.args.get('ids')

    where = []
    params = []
    if ids:
        # expect comma separated ids
        id_list = [i for i in ids.split(',') if i.strip().isdigit()]
        if id_list:
            placeholders = ','.join('?' * len(id_list))
            where.append(f'id IN ({placeholders})')
            params.extend(id_list)
    if table:
        where.append('table_name = ?')
        params.append(table)
    if action:
        where.append('action = ?')
        params.append(action)
    if user_q:
        where.append('user = ?')
        params.append(user_q)
    if q:
        where.append('(record_id = ? OR timestamp LIKE ? OR old_value LIKE ? OR new_value LIKE ?)')
        params.extend([q, f"%{q}%", f"%{q}%", f"%{q}%"])

    where_sql = ' AND '.join(where)
    if where_sql:
        where_sql = 'WHERE ' + where_sql

    conn = get_db_connection()
    rows = conn.execute(f"SELECT * FROM AuditLog {where_sql} ORDER BY id DESC", params).fetchall()
    conn.close()

    # prepare CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'timestamp', 'user', 'action', 'table_name', 'record_id', 'old_value', 'new_value', 'ip'])
    for r in rows:
        row = list(r)
        # ensure strings
        row = [row[0], row[1], row[2], row[3], row[4], row[5], row[6] or '', row[7] or '', row[8] or '']
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()

    return (csv_data, 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename="audit_logs.csv"'
    })

@app.route('/bulk_update_products', methods=['POST'])
def bulk_update_products():
    product_ids = request.form.getlist('product_ids')
    new_rate = request.form.get('new_rate')

    if not product_ids or not new_rate:
        flash("請先勾選產品並輸入新的佣金比例！", "warning")
        return redirect(url_for('manage_products'))

    conn = get_db_connection()
    # capture olds
    placeholders = ','.join('?' * len(product_ids))
    olds = conn.execute(f"SELECT * FROM Products WHERE id IN ({placeholders})", product_ids).fetchall()
    olds_list = [dict(r) for r in olds]

    sql = f"UPDATE Products SET commission_rate = ? WHERE id IN ({placeholders})"
    params = [float(new_rate)] + product_ids
    conn.execute(sql, params)
    conn.commit()

    # capture news
    news = conn.execute(f"SELECT * FROM Products WHERE id IN ({placeholders})", product_ids).fetchall()
    news_list = [dict(r) for r in news]
    try:
        log_audit('bulk_update', 'Products', record_id=None, old_value=olds_list, new_value=news_list, user=None, ip=request.remote_addr)
    except Exception:
        pass

    conn.close()
    
    flash(f"✅ 成功將 {len(product_ids)} 件產品的永久佣金比例更新為 {float(new_rate)*100}%！", "success")
    return redirect(url_for('manage_products'))

@app.route('/update_sales_record', methods=['POST'])
def update_sales_record():
    record_id = request.form.get('id')
    date = request.form.get('date')
    model = request.form.get('model', '').strip()
    quantity = int(request.form.get('quantity', 1))
    price = float(request.form.get('price', 0.0))
    promoter_name = request.form.get('promoter_name') or request.form.get('staff_name')
    location = request.form.get('location')

    if not record_id:
        return jsonify({"status": "error", "message": "缺少記錄 ID"})

    conn = get_db_connection()
    # capture old
    old = conn.execute("SELECT * FROM Sales WHERE id = ?", (record_id,)).fetchone()
    old_dict = dict(old) if old else None

    if model:
        conn.execute("INSERT OR IGNORE INTO Products (model, product_line) VALUES (?, '未分類 (單據新增)')", (model,))

    conn.execute('''
        UPDATE Sales
        SET date = ?, model = ?, quantity = ?, price = ?, promoter_name = ?, location = ?
        WHERE id = ?
    ''', (date, model, quantity, price, promoter_name, location, record_id))
    conn.commit()

    # capture new
    new = conn.execute("SELECT * FROM Sales WHERE id = ?", (record_id,)).fetchone()
    new_dict = dict(new) if new else None
    try:
        log_audit('update', 'Sales', record_id=record_id, old_value=old_dict, new_value=new_dict, user=None, ip=request.remote_addr)
    except Exception:
        pass

    conn.close()

    return jsonify({"status": "success", "message": "已更新銷售紀錄"})

@app.route('/manage_locations')
def manage_locations():
    conn = get_db_connection()
    locations = conn.execute("SELECT * FROM Locations ORDER BY region, name").fetchall()
    conn.close()
    return render_template('manage_locations.html', locations=locations)

@app.route('/add_location', methods=['POST'])
def add_location():
    name = request.form.get('name').strip()
    region = request.form.get('region')
    if name:
        conn = get_db_connection()
        try:
            cur = conn.execute("INSERT INTO Locations (name, region) VALUES (?, ?)", (name, region))
            conn.commit()
            new_id = cur.lastrowid
            # audit
            try:
                log_audit('create', 'Locations', record_id=new_id, new_value={'name': name, 'region': region}, user=None, ip=request.remote_addr)
            except Exception:
                pass
            flash(f"✅ 成功新增店鋪：{name}", "success")
        except sqlite3.IntegrityError:
            flash("⚠️ 店鋪名稱已存在", "danger")
        conn.close()
    return redirect(url_for('manage_locations'))

@app.route('/delete_location/<int:id>')
def delete_location(id):
    conn = get_db_connection()
    # capture old
    old = conn.execute("SELECT * FROM Locations WHERE id = ?", (id,)).fetchone()
    old_dict = dict(old) if old else None
    conn.execute("DELETE FROM Locations WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    try:
        log_audit('delete', 'Locations', record_id=id, old_value=old_dict, user=None, ip=request.remote_addr)
    except Exception:
        pass
    flash("🗑️ 店鋪已刪除", "info")
    return redirect(url_for('manage_locations'))

@app.route('/update_location', methods=['POST'])
def update_location():
    loc_id = request.form.get('id')
    name = request.form.get('name').strip()
    region = request.form.get('region')
    
    if loc_id and name:
        conn = get_db_connection()
        try:
            # capture old
            old = conn.execute("SELECT * FROM Locations WHERE id = ?", (loc_id,)).fetchone()
            old_dict = dict(old) if old else None

            conn.execute("UPDATE Locations SET name = ?, region = ? WHERE id = ?", (name, region, loc_id))
            conn.commit()

            # capture new
            new = conn.execute("SELECT * FROM Locations WHERE id = ?", (loc_id,)).fetchone()
            new_dict = dict(new) if new else None
            try:
                log_audit('update', 'Locations', record_id=loc_id, old_value=old_dict, new_value=new_dict, user=None, ip=request.remote_addr)
            except Exception:
                pass
            flash(f"✅ 店鋪資料已更新", "success")
        except sqlite3.IntegrityError:
            flash("⚠️ 修改失敗：店鋪名稱可能與現有重複", "danger")
        conn.close()
    return redirect(url_for('manage_locations'))

@app.route('/upload_and_import', methods=['POST'])
def upload_and_import():
    calc_month = request.form.get('calc_month') # 格式: 2026-04
    # 🌟 獲取 Checkbox 狀態：有勾選會回傳 'on'，沒勾選是 None
    update_emp = request.form.get('update_emp') == 'on'
    if 'excel_file' not in request.files:
        flash("❌ 未選擇檔案", "danger")
        return redirect(url_for('index', month=calc_month))
    
    file = request.files['excel_file']
    if file.filename == '':
        flash("❌ 未選擇檔案", "danger")
        return redirect(url_for('index', month=calc_month))

    if file:
        # 🌟 規範化檔名：YYYYMM_OriginalName.xlsx
        original_filename = secure_filename(file.filename)
        new_filename = original_filename
        file_path = os.path.join(UPLOAD_FOLDER, new_filename)
        
        # 儲存檔案到 history 資料夾
        file.save(file_path)
        
        # 🌟 重用匯入邏輯 (呼叫之前定義的處理函數)
        # 假設你已經將 rebuild_and_import 的邏輯封裝進 process_excel_import
        success, message = process_excel_import(file_path, calc_month, update_emp=update_emp)
        
        if success:
            flash(f"✅ 檔案已上傳至 history 並成功匯入數據！", "success")
        else:
            flash(f"⚠️ 檔案已上傳但匯入失敗: {message}", "warning")
            
    return redirect(url_for('index', month=calc_month))

# 🌟 API 1：獲取員工單月每日打卡紀錄
@app.route('/api/daily_attendance/<month>/<nick_name>/<path:location>')
def get_daily_attendance(month, nick_name, location):
    conn = get_db_connection()
    # 增加 location = ? 的過濾條件
    records = conn.execute('''
        SELECT id, work_date, in_time, out_time, normal_hours, actual_hours, ot_hours ,location
        FROM DailyAttendance 
        WHERE payroll_month = ? AND nick_name = ? AND location = ?
        ORDER BY work_date
    ''', (month, nick_name, location)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in records])

# 🌟 API 2：儲存修改後的每日紀錄
@app.route('/update_daily_records', methods=['POST'])
def update_daily_records():
    calc_month = request.form.get('calc_month')
    record_ids = request.form.getlist('record_id[]')
    in_times = request.form.getlist('in_time[]')
    out_times = request.form.getlist('out_time[]')
    normal_hours_list = request.form.getlist('normal_hours[]') # 🌟 接收前端傳來的常規工時
    
    conn = get_db_connection()
    # capture olds
    olds = {}
    for rid in record_ids:
        r = conn.execute('SELECT * FROM DailyAttendance WHERE id = ?', (rid,)).fetchone()
        olds[rid] = dict(r) if r else None

    for i in range(len(record_ids)):
        in_t = in_times[i]
        out_t = out_times[i]
        norm_h = float(normal_hours_list[i] or 8.0)
        
        # 🌟 重新計算實際工時與 OT
        try:
            fmt = '%H:%M'
            from datetime import datetime
            tdelta = datetime.strptime(out_t, fmt) - datetime.strptime(in_t, fmt)
            actual_h = tdelta.seconds / 3600
            # OT = 實際 - 新的常規工時
            # ✅ 修改後：移除 max，允許負數 OT
            raw_ot = actual_h - norm_h
        except:
            actual_h, raw_ot = 0, 0

        # 更新資料庫
        conn.execute('''
            UPDATE DailyAttendance 
            SET in_time = ?, out_time = ?, normal_hours = ?, actual_hours = ?, ot_hours = ? 
            WHERE id = ?
        ''', (in_t, out_t, norm_h, actual_h, raw_ot, record_ids[i]))
    
    conn.commit()
    
    # 🌟 重新整理該筆結算紀錄 (假設我們需要重新彙總，這一步非常重要)
    # 這裡需要從其中一筆 ID 找出是誰的紀錄來觸發 sync_attendance_summary
    sample = conn.execute("SELECT nick_name, location FROM DailyAttendance WHERE id = ?", (record_ids[0],)).fetchone()
    if sample:
        sync_attendance_summary(calc_month, sample['nick_name'], sample['location'])
    # capture news and log per-record updates
    try:
        for rid in record_ids:
            new = conn.execute('SELECT * FROM DailyAttendance WHERE id = ?', (rid,)).fetchone()
            new_dict = dict(new) if new else None
            log_audit('update', 'DailyAttendance', record_id=rid, old_value=olds.get(rid), new_value=new_dict, user=None, ip=request.remote_addr)
    except Exception:
        pass

    conn.close()
    flash("✅ 考勤紀錄與常規工時已更新並重新結算！", "success")
    return redirect(url_for('index', month=calc_month))

# 🌟 1. 新增單筆每日考勤
# 🌟 修改 1：新增考勤紀錄後，觸發同步
@app.route('/add_daily_attendance', methods=['POST'])
def add_daily_attendance():
    month = request.form.get('payroll_month')
    name = request.form.get('nick_name')
    date = request.form.get('work_date')
    loc = request.form.get('location')
    in_t = request.form.get('in_time')
    out_t = request.form.get('out_time')
    
    # 🌟 從前端接收常規工時，如果沒有傳則預設 8.0
    normal_h = float(request.form.get('normal_hours', 8.0))
    
    try:
        fmt = '%H:%M'
        from datetime import datetime
        tdelta = datetime.strptime(out_t, fmt) - datetime.strptime(in_t, fmt)
        actual_h = tdelta.seconds / 3600
        
        # ✅ 修改後：移除 max，允許負數 OT
        raw_ot = actual_h - normal_h
    except:
        actual_h, raw_ot = 0, 0

    conn = get_db_connection()
    cur = conn.execute('''
        INSERT INTO DailyAttendance (payroll_month, work_date, nick_name, location, in_time, out_time, normal_hours, actual_hours, ot_hours)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (month, date, name, loc, in_t, out_t, normal_h, actual_h, raw_ot))
    conn.commit()
    new_id = cur.lastrowid
    # audit
    try:
        log_audit('create', 'DailyAttendance', record_id=new_id, new_value={'payroll_month': month, 'work_date': date, 'nick_name': name, 'location': loc, 'in_time': in_t, 'out_time': out_t, 'normal_hours': normal_h, 'actual_hours': actual_h, 'ot_hours': raw_ot}, user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()
    
    sync_attendance_summary(month, name, loc)
    
    return jsonify({"status": "success", "message": "已新增考勤紀錄並同步總表"})

# 🌟 修改 2：刪除考勤紀錄後，觸發同步
@app.route('/delete_daily_attendance/<int:id>', methods=['POST'])
def delete_daily_attendance(id):
    conn = get_db_connection()
    # 必須先抓出這筆紀錄是「誰、哪個月、哪間店」，刪除後我們才知道要重算誰的帳
    record = conn.execute("SELECT payroll_month, nick_name, location FROM DailyAttendance WHERE id = ?", (id,)).fetchone()
    
    if record:
        month, name, loc = record['payroll_month'], record['nick_name'], record['location']
        # capture old for audit
        old = conn.execute("SELECT * FROM DailyAttendance WHERE id = ?", (id,)).fetchone()
        old_dict = dict(old) if old else None
        conn.execute("DELETE FROM DailyAttendance WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        
        # 🌟 關鍵：刪除後，重新彙總一次，如果都被刪光了，總表的日數就會自動變成 0
        sync_attendance_summary(month, name, loc)
        try:
            log_audit('delete', 'DailyAttendance', record_id=id, old_value=old_dict, user=None, ip=request.remote_addr)
        except Exception:
            pass
    else:
        conn.close()
        
    return jsonify({"status": "success", "message": "紀錄已刪除並重新計算總表"})

# 🌟 補回缺失的路由：更新月結微調
@app.route('/update_attendance', methods=['POST'])
def update_attendance():
    month = request.form.get('calc_month')
    name = request.form.get('nick_name')
    location = request.form.get('location') 
    
    exp = float(request.form.get('expenses', 0) or 0)
    adj = float(request.form.get('adjustment', 0) or 0)
    bonus = float(request.form.get('attendance_bonus', 0) or 0)
    
    # ✅ 接收前端傳來的本月專屬時薪
    monthly_rate_str = request.form.get('monthly_hourly_rate', '').strip()
    
    conn = get_db_connection()

    # --- 1. 處理 Attendance 微調表 ---
    old = conn.execute('SELECT * FROM Attendance WHERE payroll_month = ? AND nick_name = ? AND location = ?', (month, name, location)).fetchone()
    old_dict = dict(old) if old else None

    conn.execute('''
        INSERT OR IGNORE INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours)
        VALUES (?, ?, ?, 0, 0, 0)
    ''', (month, name, location))
    
    conn.execute('''
        UPDATE Attendance 
        SET expenses = ?, adjustment = ?, attendance_bonus = ?
        WHERE payroll_month = ? AND nick_name = ? AND location = ?
    ''', (exp, adj, bonus, month, name, location))

    # --- 2. 處理 MonthlyRates 月度時薪表 ---
    if monthly_rate_str == '':
        # 若留空，則刪除覆寫紀錄 (恢復預設)
        conn.execute('DELETE FROM MonthlyRates WHERE payroll_month = ? AND nick_name = ?', (month, name))
    else:
        monthly_rate_val = float(monthly_rate_str)
        existing = conn.execute('SELECT id FROM MonthlyRates WHERE payroll_month = ? AND nick_name = ?', (month, name)).fetchone()
        if existing:
            conn.execute('UPDATE MonthlyRates SET hourly_rate = ? WHERE payroll_month = ? AND nick_name = ?', (monthly_rate_val, month, name))
        else:
            conn.execute('INSERT INTO MonthlyRates (payroll_month, nick_name, hourly_rate) VALUES (?, ?, ?)', (month, name, monthly_rate_val))
    
    conn.commit()

    # --- 3. 稽核紀錄 ---
    new = conn.execute('SELECT * FROM Attendance WHERE payroll_month = ? AND nick_name = ? AND location = ?', (month, name, location)).fetchone()
    new_dict = dict(new) if new else None
    try:
        log_audit('update', 'Attendance_and_Rates', record_id=new_dict.get('id') if new_dict else None, old_value=old_dict, new_value=new_dict, user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()
    
    flash(f"✅ 已儲存 {name} 在 {location} 的月結微調與時薪設定", "success")
    return redirect(url_for('index', month=month))

# 🌟 1. 獲取員工單月所有銷售明細
# 🌟 修改：API 現在需要同時接收名字與地點
@app.route('/api/sales_records/<month>/<nick_name>/<location>')
def get_sales_records(month, nick_name, location):
    conn = get_db_connection()
    records = conn.execute('''
        SELECT id, date, location, model, quantity, price 
        FROM Sales 
        WHERE payroll_month = ? AND promoter_name = ? AND location = ?
        ORDER BY date
    ''', (month, nick_name, location)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in records])

# 🌟 2. 新增單筆銷售紀錄
@app.route('/add_sales_record', methods=['POST'])
def add_sales_record():
    month = request.form.get('payroll_month')
    name = request.form.get('promoter_name')
    date = request.form.get('date')
    loc = request.form.get('location')
    model = request.form.get('model').strip() # 去除前後空白
    qty = int(request.form.get('quantity', 1))
    price = float(request.form.get('price', 0.0))
    
    conn = get_db_connection()
    # 💡 數據正規化：如果輸入了一個全新的型號，自動將其加入 Products 主檔中，預設分類為「單據新增」
    if model:
        conn.execute("INSERT OR IGNORE INTO Products (model, product_line) VALUES (?, '未分類 (單據新增)')", (model,))
        
    cur = conn.execute('''
        INSERT INTO Sales (payroll_month, date, promoter_name, location, model, quantity, price)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (month, date, name, loc, model, qty, price))
    conn.commit()
    new_id = cur.lastrowid
    # audit
    try:
        log_audit('create', 'Sales', record_id=new_id, new_value={'payroll_month': month, 'date': date, 'promoter_name': name, 'location': loc, 'model': model, 'quantity': qty, 'price': price}, user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()
    return jsonify({"status": "success", "message": "已新增銷售紀錄"})

# 🌟 3. 刪除單筆銷售紀錄
@app.route('/delete_sales_record/<int:id>', methods=['POST'])
def delete_sales_record(id):
    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Sales WHERE id = ?", (id,)).fetchone()
    old_dict = dict(old) if old else None
    conn.execute("DELETE FROM Sales WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    try:
        log_audit('delete', 'Sales', record_id=id, old_value=old_dict, user=None, ip=request.remote_addr)
    except Exception:
        pass
    return jsonify({"status": "success", "message": "紀錄已刪除"})

# 🌟 4. 清空某員工在特定地點的所有銷售單據
@app.route('/delete_sales_group', methods=['POST'])
def delete_sales_group():
    month = request.form.get('month')
    promoter = request.form.get('promoter')
    location = request.form.get('location')
    
    conn = get_db_connection()
    # fetch affected rows for audit
    rows = conn.execute('SELECT * FROM Sales WHERE payroll_month = ? AND promoter_name = ? AND location = ?', (month, promoter, location)).fetchall()
    rows_list = [dict(r) for r in rows]

    conn.execute('DELETE FROM Sales WHERE payroll_month = ? AND promoter_name = ? AND location = ?', 
                 (month, promoter, location))
    conn.commit()
    conn.close()

    try:
        log_audit('delete_group', 'Sales', record_id=None, old_value=rows_list, user=None, ip=request.remote_addr)
    except Exception:
        pass

    flash(f"✅ 已清空 {promoter} 於 {location} 的所有單據", "success")
    return redirect(url_for('index', month=month))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001, debug=True )