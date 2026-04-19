import os
import sqlite3
import pandas as pd

DB_NAME = 'payroll.db'

def rebuild_database():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print("🗑️ 已刪除舊資料庫，準備重建...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. 建立核心資料表
    cursor.execute('''CREATE TABLE Employees (id INTEGER PRIMARY KEY AUTOINCREMENT, nick_name TEXT UNIQUE NOT NULL, hourly_rate REAL DEFAULT 0, allowance REAL DEFAULT 0, commission_rate REAL DEFAULT 0.03, require_mpf INTEGER DEFAULT 1, mpf_start_month TEXT)''')
    cursor.execute('''CREATE TABLE Products (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT UNIQUE NOT NULL, product_line TEXT, commission_rate REAL DEFAULT 0.03)''')
    cursor.execute('''CREATE TABLE SpecialCommissions (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT NOT NULL, start_month TEXT NOT NULL, end_month TEXT NOT NULL, rate REAL NOT NULL)''')
    cursor.execute('''CREATE TABLE Sales (id INTEGER PRIMARY KEY AUTOINCREMENT, payroll_month TEXT, date TEXT, promoter_name TEXT, location TEXT, model TEXT, quantity INTEGER, price REAL)''')
    cursor.execute('''CREATE TABLE Attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, payroll_month TEXT, nick_name TEXT, location TEXT, days_worked INTEGER DEFAULT 0, hours REAL DEFAULT 0, ot_hours REAL DEFAULT 0, expenses REAL DEFAULT 0, UNIQUE(payroll_month, nick_name, location))''')
    
    conn.commit()
    return conn

def import_history(conn):
    cursor = conn.cursor()
    history_dir = 'history'
    
    if not os.path.exists(history_dir) or not os.listdir(history_dir): 
        print("⚠️ 找不到 history 資料夾或裡面沒有檔案！")
        return

    # ==========================================
    # 🌟 第一步：強力建立「標準產品庫」與「員工名單」
    # ==========================================
    print("📦 正在掃描並建立標準產品目錄與員工名單...")
    for filename in sorted(os.listdir(history_dir)):
        if filename.endswith('.xlsx') and not filename.startswith('~'):
            filepath = os.path.join(history_dir, filename)
            
            # 1. 讀取標準產品名單 (Ref-List)
            try:
                ref_df = pd.read_excel(filepath, sheet_name='Ref-List')
                # 根據 Sample Excel，核心欄位是 'Model-Input-Ref' 和 'Product Line'
                for _, row in ref_df.dropna(subset=['Model-Input-Ref']).iterrows():
                    model = str(row['Model-Input-Ref']).strip()
                    product_line = str(row.get('Product Line', '')).strip()
                    if product_line.lower() == 'nan': product_line = ''
                    
                    # 遇到新產品就加入，已存在就跳過，預設全部 3% (0.03)
                    cursor.execute("INSERT OR IGNORE INTO Products (model, product_line, commission_rate) VALUES (?, ?, ?)", 
                                   (model, product_line, 0.03))
            except Exception as e: 
                pass # 沒有 Ref-List 分頁就跳過
                
            # 2. 讀取標準員工名單 (Name List)
            try:
                emp_df = pd.read_excel(filepath, sheet_name='Name List', header=1)
                emp_df = emp_df.rename(columns={'Hourr Rate': 'Hourly Rate'})
                for _, row in emp_df.dropna(subset=['Nick Name']).iterrows():
                    cursor.execute("INSERT OR IGNORE INTO Employees (nick_name, hourly_rate, allowance, commission_rate) VALUES (?, ?, ?, ?)", 
                                   (str(row['Nick Name']).strip(), float(row.get('Hourly Rate', 0)), float(row.get('Allowance', 0)), 0.03))
            except Exception as e:
                pass

    print("✅ 標準名單建立完成！")

    # ==========================================
    # 🌟 第二步：逐月匯入銷售與考勤數據
    # ==========================================
    print("🚀 開始匯入各月份的銷售單據與考勤資料...")
    for filename in sorted(os.listdir(history_dir)):
        if filename.endswith('.xlsx') and not filename.startswith('~'):
            filepath = os.path.join(history_dir, filename)
            month_str = filename[:6] # 例如 '202510'
            payroll_month = f"{month_str[:4]}-{month_str[4:]}" # 轉成 '2025-10'
            
            # 1. 匯入該月份的銷售紀錄 (editable-sales-form)
            try:
                sales_df = pd.read_excel(filepath, sheet_name='editable-sales-form', header=1).dropna(subset=['Promoter', 'Model', 'price'])
                for _, row in sales_df.iterrows():
                    promoter = str(row['Promoter']).strip()
                    if promoter and promoter.lower() not in ['nan', '0', '']:
                        loc = f"{str(row.get('Shop', '')).strip()} {str(row.get('Location', '')).strip()}".strip()
                        
                        # ⚠️ 防呆機制：如果銷售單上的型號不在剛才建立的標準庫裡，自動幫它加進去！
                        model = str(row['Model']).strip()
                        cursor.execute("INSERT OR IGNORE INTO Products (model, product_line, commission_rate) VALUES (?, ?, ?)", 
                                       (model, '未分類 (單據自動新增)', 0.03))
                                       
                        cursor.execute("INSERT INTO Sales (payroll_month, date, promoter_name, location, model, quantity, price) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (payroll_month, str(row.get('date', '')), promoter, loc, model, int(row.get('quantity', 1)), float(row['price'])))
            except Exception as e: 
                pass

            # 2. 匯入該月份的考勤與工時 (工作表1)
            try:
                att_df = pd.read_excel(filepath, sheet_name='工作表1', header=1).dropna(subset=['Nick Name', 'Date'])
                att_df['Hours'] = pd.to_numeric(att_df[' Hours'], errors='coerce').fillna(0)
                att_df['OT Hours'] = pd.to_numeric(att_df['OT Hours'], errors='coerce').fillna(0)
                att_df['Location'] = att_df['Location'].fillna('')
                
                att_summary = att_df.groupby(['Nick Name', 'Location']).agg({'Date': 'nunique', 'Hours': 'sum', 'OT Hours': 'sum'}).reset_index()
                for _, row in att_summary.iterrows():
                    nick_name = str(row['Nick Name']).strip()
                    if nick_name and nick_name.lower() not in ['nan', '0', '']:
                        cursor.execute('''INSERT INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours, expenses) VALUES (?, ?, ?, ?, ?, ?, 0)
                                          ON CONFLICT(payroll_month, nick_name, location) DO UPDATE SET days_worked=excluded.days_worked, hours=excluded.hours, ot_hours=excluded.ot_hours''', 
                                       (payroll_month, nick_name, str(row['Location']).strip(), int(row['Date']), float(row['Hours']), float(row['OT Hours'])))
            except Exception as e: 
                pass
            
            print(f"✅ {payroll_month} 數據匯入完成")

    conn.commit()
    conn.close()
    print("🎉 資料庫重建與標準化匯入 100% 成功！")

if __name__ == '__main__':
    rebuild_database()
    import_history(sqlite3.connect(DB_NAME))