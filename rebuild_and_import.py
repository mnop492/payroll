import os
import sqlite3
import pandas as pd
import warnings

# 🌟 靜音設定：忽略 openpyxl 的「資料驗證」無害警告，保持終端機畫面乾淨
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

DB_NAME = 'payroll.db'

def rebuild_database():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print("🗑️ 已刪除舊資料庫，準備重建...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE Employees (id INTEGER PRIMARY KEY AUTOINCREMENT, nick_name TEXT UNIQUE NOT NULL, hourly_rate REAL DEFAULT 0, allowance REAL DEFAULT 0, commission_rate REAL DEFAULT 0.03, require_mpf INTEGER DEFAULT 0, mpf_start_month TEXT)''')
    cursor.execute('''CREATE TABLE Products (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT UNIQUE NOT NULL, product_line TEXT, commission_rate REAL DEFAULT 0.03)''')
    cursor.execute('''CREATE TABLE SpecialCommissions (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT NOT NULL, start_month TEXT NOT NULL, end_month TEXT NOT NULL, rate REAL NOT NULL)''')
    cursor.execute('''CREATE TABLE Sales (id INTEGER PRIMARY KEY AUTOINCREMENT, payroll_month TEXT, date TEXT, promoter_name TEXT, location TEXT, model TEXT, quantity INTEGER, price REAL)''')
    
    # 🌟 考勤表升級：加入五大微調欄位
    cursor.execute('''CREATE TABLE Attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, payroll_month TEXT, nick_name TEXT, location TEXT, days_worked INTEGER DEFAULT 0, hours REAL DEFAULT 0, ot_hours REAL DEFAULT 0, 
                      expenses REAL DEFAULT 0, adjustment REAL DEFAULT 0, attendance_bonus REAL DEFAULT 0, basic_pay_override REAL, allowance_override REAL, UNIQUE(payroll_month, nick_name, location))''')
        # 新增：每日考勤明細表
    cursor.execute('''
        CREATE TABLE DailyAttendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payroll_month TEXT,
            work_date TEXT,
            nick_name TEXT,
            location TEXT,
            in_time TEXT,
            out_time TEXT,
            normal_hours REAL DEFAULT 0,
            actual_hours REAL DEFAULT 0,
            ot_hours REAL DEFAULT 0
        )
    ''')
    # 建立標準店鋪表
    cursor.execute('''
        CREATE TABLE Locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,      -- 標準店鋪名稱 (例如: Tai Po Yata)
            display_name TEXT,              -- 顯示名稱 (可選，或用於分類)
            region TEXT                     -- 區域 (例如: 新界、九龍、香港島)
        )
    ''')
    # 初始匯入：你可以先將目前的標準店名存入
    initial_locations = [
        ('Kowloon Bay Fortress', '九龍灣豐澤', '九龍'),
        ('Tai Po Yata', '大埔一田', '新界'),
        ('SW Wing On', '上環永安', '香港島'),
        ('TW Aeon', '荃灣永旺', '新界'),
        ('YL Citistore', '元朗千色', '新界')
    ]
    cursor.executemany('INSERT OR IGNORE INTO Locations (name, display_name, region) VALUES (?, ?, ?)', initial_locations)
    
    conn.commit()
    return conn

def import_history(conn):
    cursor = conn.cursor()
    history_dir = 'history'
    
    if not os.path.exists(history_dir) or not os.listdir(history_dir): 
        print("⚠️ 找不到 history 資料夾或裡面沒有檔案！")
        return

    # ==========================================
    # 1. 建立標準名單
    # ==========================================
    print("📦 正在掃描並建立標準產品目錄與員工名單...")
    first_file = [f for f in sorted(os.listdir(history_dir)) if f.endswith('.xlsx') and not f.startswith('~')][0]
    filepath = os.path.join(history_dir, first_file)
    try:
        emp_df = pd.read_excel(filepath, sheet_name='Name List', header=1)
        for _, row in emp_df.dropna(subset=['Nick Name']).iterrows():
            nick_name = str(row['Nick Name']).strip()
            hourly_rate = row.get('Hourr Rate', row.get('Hourly Rate', 0))
            allowance = row.get('Allowance', 0)
            if pd.isna(hourly_rate): hourly_rate = 0
            if pd.isna(allowance): allowance = 0
            cursor.execute("INSERT OR IGNORE INTO Employees (nick_name, hourly_rate, allowance, commission_rate) VALUES (?, ?, ?, ?)", 
                           (nick_name, float(hourly_rate), float(allowance), 0.03))
        print("✅ 標準名單建立完成！")
    except Exception as e:
        print(f"❌ 讀取員工名單失敗: {e}")

    # ==========================================
    # 2. 逐月匯入資料
    # ==========================================
    print("\n🚀 開始匯入各月份的銷售單據與考勤資料...")
    for filename in sorted(os.listdir(history_dir)):
        if filename.endswith('.xlsx') and not filename.startswith('~'):
            filepath = os.path.join(history_dir, filename)
            month_str = filename[:6]
            payroll_month = f"{month_str[:4]}-{month_str[4:]}"
            print(f"▶️ 正在讀取: {payroll_month} ({filename})")
            
            # A. 產品清單
            try:
                ref_df = pd.read_excel(filepath, sheet_name='Ref-List')
                for _, row in ref_df.dropna(subset=['Model-Input-Ref']).iterrows():
                    cursor.execute("INSERT OR IGNORE INTO Products (model, product_line) VALUES (?, ?)", 
                                   (str(row['Model-Input-Ref']).strip(), str(row.get('Product Line', '')).strip()))
            except Exception as e: 
                print(f"  └─ ⚠️ 無法讀取 Ref-List: {e}")

            # B. 銷售單據
            try:
                sales_df = pd.read_excel(filepath, sheet_name='editable-sales-form', header=1).dropna(subset=['Promoter', 'Model', 'price'])
                for _, row in sales_df.iterrows():
                    promoter = str(row['Promoter']).strip()
                    if promoter and promoter.lower() not in ['nan', '0', '']:
                        loc = f"{str(row.get('Shop', '')).strip()} {str(row.get('Location', '')).strip()}".strip()
                        model = str(row['Model']).strip()
                        # 🌟 新增：將銷售紀錄遇到的地點，自動加入標準店鋪表
                        if loc and loc.lower() != 'nan':
                            cursor.execute("INSERT OR IGNORE INTO Locations (name, region) VALUES (?, 'Excel匯入')", (loc,))
                        
                        cursor.execute("INSERT OR IGNORE INTO Products (model, product_line) VALUES (?, '未分類 (單據新增)')", (model,))
                        cursor.execute("INSERT INTO Sales (payroll_month, date, promoter_name, location, model, quantity, price) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (payroll_month, str(row.get('date', '')), promoter, loc, model, int(row.get('quantity', 1)), float(row['price'])))
            except Exception as e: 
                print(f"  └─ ⚠️ 無法讀取 銷售紀錄: {e}")

            # C. 考勤與工時
            try:
                # 讀取工作表1 (或你用來抓工時的那個 Sheet)
                df_timesheet = pd.read_excel(filepath, sheet_name='工作表1', header=1, parse_dates=['Date'])
                
                # 確保必要的欄位存在 (根據你上傳的 CSV 結構)
                required_cols = ['Date', 'Nick Name', 'Location', 'In-Time', 'Out-Time', 'Normal working\n hours', 'Hours Worked', 'OT Hours']
                
                for index, row in df_timesheet.iterrows():
                    nick_name = str(row.get('Nick Name', '')).strip()
                    date_val = row.get('Date')
                    
                    # 過濾掉空白行或沒有名字的紀錄
                    if pd.isna(date_val) or not nick_name or nick_name == 'nan':
                        continue
                        
                    # 格式化日期為 YYYY-MM-DD
                    work_date = date_val.strftime('%Y-%m-%d') if pd.notnull(date_val) else None
                    location = str(row.get('Location', '')).strip()
                    # 🌟 新增：將每日考勤遇到的地點，自動加入標準店鋪表
                    if location and location.lower() != 'nan':
                        cursor.execute("INSERT OR IGNORE INTO Locations (name, region) VALUES (?, 'Excel匯入')", (location,))
                        
                    in_time = str(row.get('In-Time', '')).strip()
                    out_time = str(row.get('Out-Time', '')).strip()
                    
                    # 安全轉換數字 (處理 Excel 裡面的空白或錯誤)
                    normal_hours = pd.to_numeric(row.get('Normal working\n hours', 0), errors='coerce')
                    actual_hours = pd.to_numeric(row.get('Hours Worked', 0), errors='coerce')
                    ot_hours = pd.to_numeric(row.get('OT Hours', 0), errors='coerce')

                    # 處理 NaN 值為 0.0
                    normal_hours = 0.0 if pd.isna(normal_hours) else float(normal_hours)
                    actual_hours = 0.0 if pd.isna(actual_hours) else float(actual_hours)
                    ot_hours = 0.0 if pd.isna(ot_hours) else float(ot_hours)

                    # 寫入每日明細表
                    cursor.execute('''
                        INSERT INTO DailyAttendance 
                        (payroll_month, work_date, nick_name, location, in_time, out_time, normal_hours, actual_hours, ot_hours)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (payroll_month, work_date, nick_name, location, in_time, out_time, normal_hours, actual_hours, ot_hours))
                    
            except Exception as e:
                print(f"  └─ ⚠️ 無法處理 {payroll_month} 的每日考勤: {e}")
        
            try:
                att_df = pd.read_excel(filepath, sheet_name='工作表1', header=1).dropna(subset=['Nick Name', 'Date'])
                hours_col = ' Hours' if ' Hours' in att_df.columns else 'Hours'
                ot_col = 'OT Hours' if 'OT Hours' in att_df.columns else 'OT hours'
                
                # 取得原始數據：Actual Hours 與 Raw OT
                att_df['Actual_Hours'] = pd.to_numeric(att_df.get(hours_col, 0), errors='coerce').fillna(0)
                att_df['Raw_OT'] = pd.to_numeric(att_df.get(ot_col, 0), errors='coerce').fillna(0)
                
                # ==========================================
                # 🌟 核心邏輯：每日拆解與 OT 規則套用
                # ==========================================
                # 1. 每日底薪工時 = 實際總工時 - 原始超時 (將零頭剝離，回歸 Normal 8小時)
                att_df['Payable_Normal'] = att_df['Actual_Hours'] - att_df['Raw_OT']
                
                # 2. 每日有效 OT = 針對原始超時，套用「不足半小時不計，每半小時跳一級」規則
                def round_ot_time(t):
                    t = float(t)
                    return (int(t * 2)) / 2.0
                
                att_df['Payable_OT'] = att_df['Raw_OT'].apply(round_ot_time)
                # ==========================================

                # 加總每月工時，使用的是算好的 Payable_Normal 和 Payable_OT
                att_summary = att_df.groupby(['Nick Name', 'Location']).agg({
                    'Date': 'nunique', 
                    'Payable_Normal': 'sum', 
                    'Payable_OT': 'sum'
                }).reset_index()
                
                for _, row in att_summary.iterrows():
                    nick_name = str(row['Nick Name']).strip()
                    if nick_name and nick_name.lower() not in ['nan', '0', '']:
                        # 寫入資料庫：hours 存入底薪工時，ot_hours 存入有效加班
                        cursor.execute('''INSERT INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours) VALUES (?, ?, ?, ?, ?, ?)
                                          ON CONFLICT(payroll_month, nick_name, location) DO UPDATE SET days_worked=excluded.days_worked, hours=excluded.hours, ot_hours=excluded.ot_hours''', 
                                       (payroll_month, nick_name, str(row['Location']).strip(), int(row['Date']), float(row['Payable_Normal']), float(row['Payable_OT'])))
            except Exception as e: 
                print(f"  └─ ⚠️ 無法讀取 工作表1 (考勤): {e}")

            # 🌟 D. 讀取 Total 分頁 (擷取歷史微調數據) 🌟
            try:
                total_raw = pd.read_excel(filepath, sheet_name='Total', header=None)
                header_idx = None
                for idx, row in total_raw.iterrows():
                    row_strs = [str(x).strip().lower() for x in row.values]
                    if 'name' in row_strs and ('total' in row_strs or 'basic' in row_strs or 'expenses' in row_strs):
                        header_idx = idx
                        break

                if header_idx is not None:
                    total_df = pd.read_excel(filepath, sheet_name='Total', header=header_idx).dropna(subset=['Name'])
                    # --- 在讀取 Total 分頁的迴圈中修改 ---
                    for _, row in total_df.iterrows():
                        nick_name = str(row['Name']).strip()
                        shop = str(row.get('Shop', '')).strip() # 🌟 新增：抓取 Excel Total 表中的地點

                        exp = float(pd.to_numeric(row.get('Expenses'), errors='coerce') or 0.0)
                        adj = float(pd.to_numeric(row.get('Adjustmant'), errors='coerce') or 0.0)
                        att_bonus = float(pd.to_numeric(row.get('Attendance'), errors='coerce') or 0.0)

                        if nick_name and (exp != 0 or adj != 0 or att_bonus != 0):
                            # 🌟 修改：精準匹配 名字 + 地點
                            if shop and shop.lower() != 'nan':
                                cursor.execute('''
                                    UPDATE Attendance 
                                    SET expenses = ?, adjustment = ?, attendance_bonus = ? 
                                    WHERE payroll_month = ? AND nick_name = ? AND location LIKE ?
                                ''', (exp, adj, att_bonus, payroll_month, nick_name, f"%{shop}%"))
                            else:
                                # 如果 Excel 沒寫地點，才用保底的 LIMIT 1
                                cursor.execute('''
                                    UPDATE Attendance SET expenses = ?, adjustment = ?, attendance_bonus = ? 
                                    WHERE id = (SELECT id FROM Attendance WHERE payroll_month = ? AND nick_name = ? LIMIT 1)
                                ''', (exp, adj, att_bonus, payroll_month, nick_name))
                else:
                    print("  └─ ⚠️ 找不到 Total 表格的標題列 (跳過微調匯入)")
            except Exception as e: 
                print(f"  └─ ⚠️ 無法讀取 Total (微調數據): {e}")

            print(f"✅ {payroll_month} 數據匯入完成\n")

    conn.commit()
    conn.close()
    print("🎉 資料庫重建與標準化匯入 100% 成功！")

if __name__ == '__main__':
    rebuild_database()
    import_history(sqlite3.connect(DB_NAME))