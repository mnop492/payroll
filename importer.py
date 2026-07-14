import sqlite3
import pandas as pd
import math
import re

def get_db_connection():
    conn = sqlite3.connect('payroll.db')
    conn.row_factory = sqlite3.Row
    return conn

# 🌟 新增：終極字串淨化函數 (殺死所有隱形空格與多餘空白)
def clean_text(text, is_name=False):
    if pd.isna(text) or text is None:
        return ""
    text_str = str(text)
    if text_str.strip().lower() == 'nan':
        return ""
    
    # 核心魔法：把所有的全形空白、tab、連續多個空白，通通替換成一個標準的半形空白，然後去頭去尾
    cleaned = re.sub(r'\s+', ' ', text_str).strip()
    
    # 如果是人名，強制把每個單字字首大寫 (apple -> Apple, irene -> Irene)
    if is_name and cleaned:
        return cleaned.title()
    return cleaned

def process_excel_import(file_path, payroll_month, update_emp=True):
    """
    從 Excel 匯入單月資料的核心邏輯
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # ==========================================
        # A. 處理員工名單 (Name List) - 🌟 增加判斷開關
        # ==========================================
        if update_emp:
            emp_df = pd.read_excel(file_path, sheet_name='Name List', header=1).dropna(subset=['Nick Name'])
            for _, row in emp_df.iterrows():
                nick_name = clean_text(row.get('Nick Name'), is_name=True)
                if not nick_name: continue
                
                h_rate = float(pd.to_numeric(row.get('Hourly Rate', row.get('Hourr Rate', 0)), errors='coerce') or 0.0)
                allowance = float(pd.to_numeric(row.get('Allowance', 0), errors='coerce') or 0.0)

                # 讀取佣金比例：清理 "3%%" 之類的格式錯誤
                raw_comm = row.get('rate', row.get('Rate', None))
                comm_rate = 0.03  # 預設值
                if raw_comm is not None and not pd.isna(raw_comm):
                    comm_str = str(raw_comm).strip().replace('%', '')
                    try:
                        comm_val = float(comm_str)
                        # 若輸入的是百分比整數 (e.g. 3 代表 3%)，自動轉換
                        comm_rate = comm_val / 100.0 if comm_val > 1 else comm_val
                    except ValueError:
                        comm_rate = 0.03

                # 新員工：建立 Employees 記錄（不覆蓋既有員工的全域預設時薪）
                cursor.execute('''
                    INSERT INTO Employees (nick_name, hourly_rate, allowance, commission_rate) 
                    VALUES (?, ?, ?, 0.03)
                    ON CONFLICT(nick_name) DO NOTHING
                ''', (nick_name, h_rate, allowance))

                # 把本月時薪/津貼/佣金比例寫入 MonthlyRates（月度覆蓋，不影響其他月份）
                cursor.execute('''
                    INSERT INTO MonthlyRates (payroll_month, nick_name, hourly_rate, allowance, commission_rate)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(payroll_month, nick_name) DO UPDATE SET
                        hourly_rate = excluded.hourly_rate,
                        allowance = excluded.allowance,
                        commission_rate = excluded.commission_rate
                ''', (payroll_month, nick_name, h_rate, allowance, comm_rate))

        # ==========================================
        # B & C. 處理考勤明細 (工作表1) 並彙總至 Attendance
        # ==========================================
        cursor.execute("DELETE FROM DailyAttendance WHERE payroll_month = ?", (payroll_month,))
        cursor.execute("DELETE FROM Attendance WHERE payroll_month = ?", (payroll_month,))
        
        df_timesheet = pd.read_excel(file_path, sheet_name='工作表1', header=1, parse_dates=['Date'])
        
        # 用於存放「每人、每店」的月結加總
        monthly_att = {}

        for _, row in df_timesheet.iterrows():
            nick_name = str(row.get('Nick Name', '')).strip()
            if not nick_name or nick_name == 'nan': continue
            
            loc = str(row.get('Location', '')).strip()
            if loc: cursor.execute("INSERT OR IGNORE INTO Locations (name, region) VALUES (?, 'Excel匯入')", (loc,))
            
            # 抓取工時欄位
            normal_h = float(pd.to_numeric(row.get('Normal working\n hours', row.get('Normal Hours', 0)), errors='coerce') or 0)
            actual_h = float(pd.to_numeric(row.get(' Hours', row.get('Hours', row.get('Hours Worked', 0))), errors='coerce') or 0)
            raw_ot_h = float(pd.to_numeric(row.get('OT Hours', row.get('OT hours', 0)), errors='coerce') or 0)
            
            # 🌟 OT 半小時進位淨化規則
            clean_ot_h = 0.0
            if raw_ot_h >= 0.5:
                clean_ot_h = math.floor(raw_ot_h / 0.5) * 0.5
            
            # 底薪工時 = 實際總工時 - 原始 OT
            payable_normal = actual_h - raw_ot_h

            # 1. 寫入 DailyAttendance
            cursor.execute('''
                INSERT INTO DailyAttendance (payroll_month, work_date, nick_name, location, in_time, out_time, normal_hours, actual_hours, ot_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (payroll_month, row['Date'].strftime('%Y-%m-%d'), nick_name, loc, str(row.get('In-Time', '')), str(row.get('Out-Time', '')), 
                  normal_h, actual_h, clean_ot_h))

            # 2. 累計總數
            key = (nick_name, loc)
            if key not in monthly_att:
                monthly_att[key] = {'days': 0, 'hours': 0.0, 'ot': 0.0}
            monthly_att[key]['days'] += 1
            monthly_att[key]['hours'] += payable_normal
            monthly_att[key]['ot'] += clean_ot_h

        # 寫入 Attendance 總表
        for (nick_name, loc), totals in monthly_att.items():
            cursor.execute('''
                INSERT INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (payroll_month, nick_name, loc, totals['days'], totals['hours'], totals['ot']))

        # ==========================================
        # D. 從 Total 分頁抄寫 4 大金錢欄位
        # ==========================================
        try:
            total_raw = pd.read_excel(file_path, sheet_name='Total', header=None)
            header_idx = None
            for idx, row_data in total_raw.iterrows():
                row_strs = [str(x).strip().lower() for x in row_data.values]
                if 'name' in row_strs and ('total' in row_strs or 'basic' in row_strs):
                    header_idx = idx
                    break

            if header_idx is not None:
                total_df = pd.read_excel(file_path, sheet_name='Total', header=header_idx).dropna(subset=['Name'])
                for _, row in total_df.iterrows():
                    name = str(row['Name']).strip()
                    if not name or name.lower() == 'nan': continue
                    shop = str(row.get('Shop', '')).strip()
                    
                    # 抓取指定 4 欄
                    att_bonus = float(pd.to_numeric(row.get('Attendance'), errors='coerce') or 0.0)
                    allowance_ov = float(pd.to_numeric(row.get('Allowance'), errors='coerce') or 0.0)
                    expenses = float(pd.to_numeric(row.get('Expenses'), errors='coerce') or 0.0)
                    adj = float(pd.to_numeric(row.get('Adjustmant', row.get('Adjustment')), errors='coerce') or 0.0)

                    if any(v != 0 for v in [att_bonus, allowance_ov, expenses, adj]):
                        cursor.execute('''
                            UPDATE Attendance 
                            SET attendance_bonus = ?, allowance_override = ?, expenses = ?, adjustment = ?
                            WHERE payroll_month = ? AND nick_name = ? AND location LIKE ?
                        ''', (att_bonus, allowance_ov, expenses, adj, payroll_month, name, f"%{shop}%"))
        except Exception as e:
            print(f"Total 分頁讀取異常: {e}")

        # ==========================================
        # E. 處理銷售紀錄
        # ==========================================
        cursor.execute("DELETE FROM Sales WHERE payroll_month = ?", (payroll_month,))
        sales_df = pd.read_excel(file_path, sheet_name='editable-sales-form', header=1).dropna(subset=['Promoter', 'Model'])
        for _, row in sales_df.iterrows():
            promoter = str(row['Promoter']).strip()
            if promoter.lower() in ['nan', '0', '']: continue
            loc = f"{str(row.get('Shop', '')).strip()} {str(row.get('Location', '')).strip()}".strip()
            model = str(row['Model']).strip()
            cursor.execute("INSERT OR IGNORE INTO Products (model, product_line) VALUES (?, '未分類')", (model,))
            cursor.execute('''
                INSERT INTO Sales (payroll_month, date, promoter_name, location, model, quantity, price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (payroll_month, str(row.get('date', '')), promoter, loc, model, int(row.get('quantity', 1)), float(row.get('price', 0))))

        conn.commit()
        return True, "✅ 匯入成功：員工時薪、工時總計與微調已同步更新。"
    except Exception as e:
        conn.rollback()
        return False, f"❌ 匯入失敗: {str(e)}"
    finally:
        conn.close()