import pandas as pd
import sqlite3
import logging
import os

def get_db_connection():
    conn = sqlite3.connect('payroll.db')
    conn.row_factory = sqlite3.Row
    return conn

def process_payroll_from_db(calc_month):
    try:
        # 使用 pandas 直接讀取 sqlite，這裡用標準 connection
        conn = sqlite3.connect('payroll.db')
        
        # 1. 讀取基礎資料表 (員工與產品)
        employees_df = pd.read_sql_query("SELECT * FROM Employees", conn)
        products_df = pd.read_sql_query("SELECT * FROM Products", conn)
        
        # 🌟 讀取特佣規則 (加入 try-except 容錯，防禦資料表還沒建立的情況)
        try:
            special_comm_df = pd.read_sql_query("SELECT * FROM SpecialCommissions", conn)
        except Exception:
            special_comm_df = pd.DataFrame(columns=['model', 'start_month', 'end_month', 'rate'])

        # 2. 讀取當月單據與考勤資料
        sales_db_df = pd.read_sql_query("SELECT * FROM Sales WHERE payroll_month = ?", conn, params=(calc_month,))
        attendance_df = pd.read_sql_query("SELECT nick_name AS 'Nick Name', location AS 'Location', days_worked AS 'Days', hours AS 'Hours', ot_hours AS 'OT Hours', expenses AS 'Expenses' FROM Attendance WHERE payroll_month = ?", conn, params=(calc_month,))
        conn.close()

        # ==========================================
        # 第一步：處理考勤與津貼數據
        # ==========================================
        if not attendance_df.empty:
            attendance_df['Days'] = pd.to_numeric(attendance_df['Days'], errors='coerce').fillna(0)
            attendance_df['Hours'] = pd.to_numeric(attendance_df['Hours'], errors='coerce').fillna(0)
            attendance_df['OT Hours'] = pd.to_numeric(attendance_df['OT Hours'], errors='coerce').fillna(0)
            # 相同名字與地點的紀錄加總
            att_summary = attendance_df.groupby(['Nick Name', 'Location']).agg({'Days': 'sum', 'Hours': 'sum', 'OT Hours': 'sum', 'Expenses': 'sum'}).reset_index()
        else:
            att_summary = pd.DataFrame(columns=['Nick Name', 'Location', 'Days', 'Hours', 'OT Hours'])

        # ==========================================
        # 第二步：處理銷售與動態佣金計算
        # ==========================================
        if not sales_db_df.empty:
            # 先合併基礎產品資訊，取得預設 commission_rate
            merged_sales = pd.merge(sales_db_df, products_df, left_on='model', right_on='model', how='left')
            merged_sales['commission_rate'] = merged_sales['commission_rate'].fillna(0.03) # 找不到產品就預設 3%
            
            # 🌟 核心特佣邏輯：決定每一筆單據的最終佣金比例
            def get_effective_rate(row):
                base_rate = row['commission_rate']
                model = str(row['model']).strip()
                
                if not special_comm_df.empty:
                    # 在特佣表中尋找：型號一致，且計糧月份落在特佣區間內
                    match = special_comm_df[
                        (special_comm_df['model'].str.strip() == model) & 
                        (special_comm_df['start_month'] <= calc_month) & 
                        (special_comm_df['end_month'] >= calc_month)
                    ]
                    if not match.empty:
                        return float(match.iloc[0]['rate']) # 優先使用特佣比例
                return base_rate # 沒特佣就用基礎比例

            merged_sales['effective_rate'] = merged_sales.apply(get_effective_rate, axis=1)
            
            # 計算該筆單據佣金
            merged_sales['Sub_Total_Sales'] = merged_sales['quantity'] * merged_sales['price']
            merged_sales['Calc_Comm'] = merged_sales['Sub_Total_Sales'] * merged_sales['effective_rate']
            
            # 依員工與地點加總佣金
            sales_summary = merged_sales.groupby(['promoter_name', 'location']).agg({'Sub_Total_Sales': 'sum', 'Calc_Comm': 'sum'}).reset_index()
        else:
            sales_summary = pd.DataFrame(columns=['promoter_name', 'location', 'Sub_Total_Sales', 'Calc_Comm'])

        # ==========================================
        # 第三步：名單合併與薪資總計
        # ==========================================
        # 萃取所有出現過的人名與地點（確保有打卡沒賣東西，或有賣東西沒打卡的人都不會漏掉）
        att_keys = att_summary[['Nick Name', 'Location']].rename(columns={'Nick Name': 'Name'})
        sales_keys = sales_summary[['promoter_name', 'location']].rename(columns={'promoter_name': 'Name', 'location': 'Location'})
        all_keys = pd.concat([att_keys, sales_keys]).drop_duplicates()

        # 清理空格，準備合併
        all_keys['Name'] = all_keys['Name'].str.strip()
        employees_df['nick_name'] = employees_df['nick_name'].str.strip()
        att_summary['Nick Name'] = att_summary['Nick Name'].str.strip()
        sales_summary['promoter_name'] = sales_summary['promoter_name'].str.strip()

        if all_keys.empty:
            return False, f"找不到 {calc_month} 的紀錄", None, None

        # 以 all_keys 為骨幹，把員工基本資料、考勤、銷售數據貼上去
        final_df = pd.merge(all_keys, employees_df, left_on='Name', right_on='nick_name', how='left')
        final_df = pd.merge(final_df, att_summary, left_on=['Name', 'Location'], right_on=['Nick Name', 'Location'], how='left').fillna({'Days': 0, 'Hours': 0, 'OT Hours': 0})
        final_df = pd.merge(final_df, sales_summary, left_on=['Name', 'Location'], right_on=['promoter_name', 'location'], how='left').fillna({'Calc_Comm': 0})

        # 計算薪水
        final_df['hourly_rate'] = final_df['hourly_rate'].fillna(0)
        final_df['allowance'] = final_df['allowance'].fillna(0)
        
        # 🌟 津貼 = 日數 x 設定的 allowance 金額
        final_df['Total_Allowance'] = final_df['Days'] * final_df['allowance']
        final_df['Basic Pay'] = (final_df['Hours'] + final_df['OT Hours']) * final_df['hourly_rate']
        final_df['Expenses'] = final_df['Expenses'].fillna(0)
        final_df['Gross Pay'] = final_df['Basic Pay'] + final_df['Calc_Comm'] + final_df['Total_Allowance'] + final_df['Expenses']

        # ==========================================
        # 第四步：MPF 特例與標準邏輯判斷
        # ==========================================
        def calculate_mpf(row):
            gross = row['Gross Pay']
            # 取得該員工設定的 MPF 起始月份 (如 Wah 的 2026-04)
            mpf_start = row.get('mpf_start_month')
            
            # 🌟 特例 1：如果沒設定起始月份，或者目前結算月份「小於」起始月份，一律不扣
            if pd.isna(mpf_start) or not str(mpf_start).strip() or calc_month < str(mpf_start).strip():
                return 0.0, "豁免期"
                
            # 🌟 特例 2：已經到了起始月份，根據香港法例標準扣除
            if gross < 7100: 
                return 0.0, "未達門檻"
            elif gross > 30000: 
                return 1500.0, "達上限"
            else: 
                return round(gross * 0.05, 2), "正常扣除"
        
        # apply 函數會回傳一組 (金額, 狀態文字)，我們把它拆開放入兩個欄位
        mpf_results = final_df.apply(calculate_mpf, axis=1)
        final_df['MPF'] = [res[0] for res in mpf_results]
        final_df['MPF狀態'] = [res[1] for res in mpf_results]
        
        final_df['Net Pay'] = final_df['Gross Pay'] - final_df['MPF']

        # ==========================================
        # 第五步：整理輸出格式
        # ==========================================
        display_df = final_df[['Name', 'Hours', 'OT Hours', 'Basic Pay', 'Calc_Comm', 'Total_Allowance', 'Gross Pay', 'MPF', 'MPF狀態', 'Net Pay', 'Location']]
        display_df.columns = ['員工', '工時', 'OT工時', '底薪', '總佣金', '津貼', '總收入', 'MPF扣除', 'MPF狀態', '實發薪資', '地點']

        # 強制四捨五入到小數點後兩位
        cols_to_round = ['工時', 'OT工時', '底薪', '總佣金', '津貼', '總收入', 'MPF扣除', '實發薪資']
        display_df[cols_to_round] = display_df[cols_to_round].round(2)

        # 輸出為 Excel (供下載備份)
        output_folder = 'outputs'
        os.makedirs(output_folder, exist_ok=True)
        output_filename = f'Payroll_Summary_{calc_month}.xlsx'
        output_path = os.path.join(output_folder, output_filename)
        display_df.to_excel(output_path, index=False)
        
        # 將 DataFrame 轉為字典清單傳給 Flask 前端
        records = display_df.to_dict(orient='records')
        
        return True, "計算成功", records, output_filename

    except Exception as e:
        logging.error(f"計糧引擎錯誤: {str(e)}")
        return False, f"計算失敗: {str(e)}", None, None