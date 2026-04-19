import os
import sqlite3
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
import pandas as pd
from datetime import datetime # 🌟 新增這行：引入時間套件
from payroll_engine import process_payroll_from_db # 確保匯入名稱正確

app = Flask(__name__)
app.secret_key = "super_secret_key"

UPLOAD_FOLDER = 'uploads'
LOG_FOLDER = 'logs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_FOLDER, 'system.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- 新增：資料庫連線小工具 ---
def get_db_connection():
    conn = sqlite3.connect('payroll.db')
    conn.row_factory = sqlite3.Row  # 讓回傳的資料可以像字典一樣操作
    return conn

@app.route('/')
def index():
    current_month = request.args.get('month', pd.Timestamp.now().strftime('%Y-%m'))
    conn = get_db_connection()
    # 讀取銷售紀錄
    records = conn.execute("SELECT * FROM Sales WHERE payroll_month = ?", (current_month,)).fetchall()
    # 🌟 新增：讀取考勤紀錄
    attendances = conn.execute("SELECT * FROM Attendance WHERE payroll_month = ?", (current_month,)).fetchall()
    conn.close()
    return render_template('index.html', current_month=current_month, records=records, attendances=attendances)

# 2. 在 app.py 任何地方，加入這個刪除考勤的路由：
@app.route('/delete_attendance/<int:id>', methods=['POST'])
def delete_attendance(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM Attendance WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("考勤紀錄已刪除", "success")
    return redirect(request.referrer or url_for('index'))

# 在 app.py 找到 insert_record 並加入 location 接收
@app.route('/insert_record', methods=['POST'])
def insert_record():
    payroll_month = request.form.get('payroll_month')
    date = request.form.get('date')
    promoter = request.form.get('promoter')
    location = request.form.get('location') # 🌟 新增這行
    model = request.form.get('model')
    quantity = request.form.get('quantity')
    price = request.form.get('price')

    conn = get_db_connection()
    conn.execute('''
        INSERT INTO Sales (payroll_month, date, promoter_name, location, model, quantity, price)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (payroll_month, date, promoter, location, model, quantity, price))
    conn.commit()
    conn.close()
    # ... 下面維持不變 ...

    logging.info(f"成功寫入單據 - 月份: {payroll_month}, 員工: {promoter}")
    flash(f'成功新增一筆 {promoter} 的紀錄 ({payroll_month})！', 'success')
    return redirect(url_for('index'))

# 👇 修改：一鍵計糧路由 (不再需要上傳 Excel 檔案了！)
@app.route('/calculate_payroll', methods=['POST'])
def calculate_payroll():
    calc_month = request.form.get('calc_month')
    
    # 直接呼叫引擎，不傳檔案路徑
    success, message, records, output_file = process_payroll_from_db(calc_month)
    
    if success:
        flash(f'{calc_month} 月份計算成功！', 'success')
        # 修改 app.py 裡的這一行
        return render_template('result.html', records=records, output_file=output_file, calc_month=calc_month)
    else:
        flash(message, 'danger')
        return redirect(url_for('index'))

@app.route('/delete_record/<int:record_id>', methods=['POST'])
def delete_record(record_id):
    conn = get_db_connection()
    # 根據資料表的 ID 來刪除該筆紀錄
    conn.execute('DELETE FROM Sales WHERE id = ?', (record_id,))
    conn.commit()
    conn.close()

    logging.info(f"已刪除銷售紀錄 ID: {record_id}")
    flash(f'紀錄 (ID: {record_id}) 已成功刪除！', 'warning')
    return redirect(url_for('index'))

# 修改 app.py 裡的單獨糧單路由
@app.route('/view_payslip/<int:idx>/<month>')
def view_payslip(idx, month):
    from payroll_engine import process_payroll_from_db
    
    # 呼叫引擎算好該月的所有 records
    success, message, records, _ = process_payroll_from_db(month)
    
    if success and idx < len(records):
        # 🌟 透過索引 (idx) 直接精準定位，不論名字或地點有沒有空格 🌟
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
    days = request.form.get('days_worked', 0) # 🌟 接收日數
    hours = request.form.get('hours', 0)
    ot_hours = request.form.get('ot_hours', 0)
    expenses = request.form.get('expenses', 0)
    
    conn = get_db_connection()
    # 加上讀取 expenses，並存入資料庫


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

# 👇 新增：一鍵生成全公司糧單的路由
@app.route('/print_all/<calc_month>')
def print_all_payslips(calc_month):
    # 直接呼叫我們寫好的引擎，重新抓取該月份的所有算好資料
    from payroll_engine import process_payroll_from_db
    success, message, records, output_file = process_payroll_from_db(calc_month)
    
    if not success or not records:
        flash(f'找不到 {calc_month} 的薪資資料，請先計算！', 'danger')
        return redirect(url_for('index'))
        
    # 將所有人的資料傳給新的 print_all.html 模板
    return render_template('print_all.html', records=records, month=calc_month)

@app.route('/validate')
def validate_data():
    results = perform_validation() # 封裝邏輯以便重用
    return render_template('validation.html', results=results)

@app.route('/download_validation')
def download_validation():
    results = perform_validation()
    df = pd.DataFrame(results)
    
    # 整理 Excel 欄位名稱
    df.columns = ['月份', '員工', '地點', 'Excel底薪', '系統底薪', 'Excel佣金', '系統佣金', 
                  'Excel津貼', '系統津貼', 'Excel_MPF', '系統_MPF', 'Excel實發', '系統實發', '差異', '狀態']
    
    output_path = 'outputs/Validation_Report.xlsx'
    df.to_excel(output_path, index=False)
    return send_from_directory('outputs', 'Validation_Report.xlsx', as_attachment=True)

def perform_validation():
    from payroll_engine import process_payroll_from_db
    import os
    
    history_dir = 'history'
    validation_results = []
    
    if not os.path.exists(history_dir): return []

    for filename in sorted(os.listdir(history_dir)):
        if filename.endswith('.xlsx') and not filename.startswith('~'):
            month_str = filename[:6]
            payroll_month = f"{month_str[:4]}-{month_str[4:]}"
            success, _, sys_records, _ = process_payroll_from_db(payroll_month)
            if not success: continue
            
            try:
                filepath = os.path.join(history_dir, filename)
                # 讀取 Total 頁面，標題在第 7 行 (index 6)
                ex_df = pd.read_excel(filepath, sheet_name='Total', header=6)
                ex_df.columns = ex_df.columns.astype(str).str.strip()
                # 關鍵欄位對應：Name, Shop, 酬  金 (或底薪), Basic Comm (佣金), Allowance, MPF, Total
                ex_df = ex_df.dropna(subset=['Name', 'Total'])
            except: continue

            for _, ex_row in ex_df.iterrows():
                name = str(ex_row['Name']).strip()
                loc = str(ex_row.get('Shop', '')).strip()
                
                # 提取 Excel 各項數值 (處理可能出現的 NaN)
                ex_vals = {
                    'basic': round(float(ex_row.get('酬  金', 0)), 0),
                    'comm': round(float(ex_row.get('Basic Comm', 0)), 0),
                    'allow': round(float(ex_row.get('Allowance', 0)), 0),
                    'mpf': round(float(ex_row.get('MPF', 0)), 0),
                    'net': round(float(ex_row['Total']), 0)
                }

                # 尋找系統匹配項
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

# 1. 進入設定頁面：顯示目前的特佣規則與員工清單
@app.route('/settings')
def settings():
    conn = get_db_connection()
    # 讀取所有特殊佣金規則
    special_comms = conn.execute("SELECT * FROM SpecialCommissions").fetchall()
    # 讀取所有員工，用於設定 MPF 開始月份
    employees = conn.execute("SELECT * FROM Employees").fetchall()
    conn.close()
    return render_template('settings.html', special_comms=special_comms, employees=employees)

# 2. 儲存特殊佣金規則
@app.route('/save_special_comm', methods=['POST'])
def save_special_comm():
    model = request.form.get('model').strip()
    start = request.form.get('start')
    end = request.form.get('end')
    rate = request.form.get('rate')
    
    conn = get_db_connection()
    conn.execute("INSERT INTO SpecialCommissions (model, start_month, end_month, rate) VALUES (?, ?, ?, ?)",
                 (model, start, end, float(rate)))
    conn.commit()
    conn.close()
    flash(f"已成功加入 {model} 的特殊佣金規則", "success")
    return redirect(url_for('settings'))

# 3. 刪除特殊佣金規則
@app.route('/delete_special_comm/<int:id>')
def delete_special_comm(id):
    conn = get_db_connection()
    # 確保是從 SpecialCommissions 表刪除
    conn.execute("DELETE FROM SpecialCommissions WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    
    # 🌟 自動返回觸發刪除的頁面 (即管理頁面)
    return redirect(request.referrer or url_for('manage_products'))

# 4. 更新員工 MPF 開始月份
@app.route('/update_emp_mpf', methods=['POST'])
def update_emp_mpf():
    name = request.form.get('name')
    start_month = request.form.get('start_month')
    
    conn = get_db_connection()
    conn.execute("UPDATE Employees SET mpf_start_month = ? WHERE nick_name = ?", (start_month, name))
    conn.commit()
    conn.close()
    flash(f"已更新 {name} 的 MPF 起扣月份", "success")
    return redirect(url_for('settings'))

# ==========================================
# 產品與佣金批量管理
# ==========================================
# app.py 新增路由

@app.route('/manage_products')
def manage_products():
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM Products ORDER BY model").fetchall()
    # 同時讀取所有特佣規則，方便在頁面顯示
    special_rules = conn.execute("SELECT * FROM SpecialCommissions ORDER BY start_month DESC").fetchall()
    conn.close()
    return render_template('manage_products.html', products=products, special_rules=special_rules)

@app.route('/update_product_config', methods=['POST'])
def update_product_config():
    model = request.form.get('model')
    update_type = request.form.get('update_type') # 'permanent' 或 'special'
    rate = float(request.form.get('rate'))
    
    conn = get_db_connection()
    if update_type == 'permanent':
        # 更新 Products 表的預設比例
        conn.execute("UPDATE Products SET commission_rate = ? WHERE model = ?", (rate, model))
        flash(f"✅ 已更新 {model} 的永久佣金比例為 {rate*100}%", "success")
    else:
        # 新增到 SpecialCommissions 表
        start = request.form.get('start_month')
        end = request.form.get('end_month')
        if not start or not end:
            flash("❌ 設定特佣時必須填寫開始與結束月份", "danger")
            return redirect(url_for('manage_products'))
        
        conn.execute("INSERT INTO SpecialCommissions (model, start_month, end_month, rate) VALUES (?, ?, ?, ?)",
                     (model, start, end, rate))
        flash(f"✅ 已成功為 {model} 加入特佣規則 ({start} 至 {end})", "success")
    
    conn.commit()
    conn.close()
    return redirect(url_for('manage_products'))

@app.route('/bulk_update_products', methods=['POST'])
def bulk_update_products():
    # 獲取打勾的產品 ID 列表
    product_ids = request.form.getlist('product_ids')
    new_rate = request.form.get('new_rate')

    if not product_ids or not new_rate:
        flash("請先勾選產品並輸入新的佣金比例！", "warning")
        return redirect(url_for('manage_products'))

    conn = get_db_connection()
    # 根據打勾的數量，動態生成 SQL 語句
    placeholders = ','.join('?' * len(product_ids))
    sql = f"UPDATE Products SET commission_rate = ? WHERE id IN ({placeholders})"
    
    # 參數：[新比例, id1, id2, id3...]
    params = [float(new_rate)] + product_ids
    conn.execute(sql, params)
    conn.commit()
    conn.close()
    
    flash(f"✅ 成功將 {len(product_ids)} 件產品的永久佣金比例更新為 {float(new_rate)*100}%！", "success")
    return redirect(url_for('manage_products'))

# app.py 新增路由

@app.route('/update_sales_record', methods=['POST'])
def update_sales_record():
    record_id = request.form.get('id')
    model = request.form.get('model')
    quantity = int(request.form.get('quantity'))
    month = request.form.get('month')
    staff_name = request.form.get('staff_name')
    location = request.form.get('location')

    conn = get_db_connection()
    conn.execute('''
        UPDATE SalesRecords 
        SET model = ?, quantity = ?, month = ?, staff_name = ?, location = ?
        WHERE id = ?
    ''', (model, quantity, month, staff_name, location, record_id))
    conn.commit()
    conn.close()
    
    flash(f"✅ 已成功更新 {staff_name} 的銷售紀錄", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)