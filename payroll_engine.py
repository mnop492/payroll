import sqlite3
import pandas as pd
import math  # 🌟 新增：用於精準計算 OT 進位

def process_payroll_from_db(calc_month, db_path='payroll.db'):
    """
    安全升級版計糧大腦：支援五大彈性微調，並保證不漏算任何員工
    """
    conn = sqlite3.connect(db_path)
    
    # ==========================================
    # 1. 讀取所需資料庫
    # ==========================================
    emp_df = pd.read_sql_query("SELECT nick_name AS Name, hourly_rate, allowance, commission_rate AS default_comm, require_mpf, mpf_start_month, full_name FROM Employees", conn)
    
    # ==========================================
    # 2. 讀取考勤與每日明細 (🌟 升級版每日 OT 結算)
    # ==========================================
    # A. 先讀取「每日打卡明細」
    daily_df = pd.read_sql_query("""
        SELECT nick_name AS Name, location AS Location, actual_hours, normal_hours, ot_hours AS raw_ot
        FROM DailyAttendance 
        WHERE payroll_month = ?
    """, conn, params=(calc_month,))

    # B. 讀取原本 Attendance 表中的「五大金剛微調」與「津貼」
    adj_df = pd.read_sql_query("""
        SELECT nick_name AS Name, location AS Location, 
               expenses, adjustment, attendance_bonus, basic_pay_override, allowance_override 
        FROM Attendance WHERE payroll_month = ?
    """, conn, params=(calc_month,))

    if not daily_df.empty:
        # 🌟 核心 OT 規則：不足半小時不計，每半小時跳一級
        def apply_clean_ot(raw_ot):
            if pd.isna(raw_ot) or raw_ot < 0.5:
                return 0.0
            # math.floor 向下取整：例如 0.9 / 0.5 = 1.8 -> floor(1.8) = 1 -> 1 * 0.5 = 0.5
            return math.floor(raw_ot / 0.5) * 0.5

        # 逐日清洗 OT 數據
        daily_df['Clean_OT'] = daily_df['raw_ot'].apply(apply_clean_ot)
        
        # 每日應付底薪工時 = 實際打卡工時 - 原始OT (回歸表定正常工時)
        daily_df['Payable_Normal'] = daily_df['normal_hours']

        # 針對每位員工在各店鋪進行「按月加總」
        att_summary = daily_df.groupby(['Name', 'Location']).agg(
            Days=('Payable_Normal', 'size'),    # 計算返工日數
            Hours=('Payable_Normal', 'sum'),    # 總底薪工時
            OT_Hours=('Clean_OT', 'sum')        # 🌟 總結算後的最乾淨 OT
        ).reset_index()
        
        # 重新命名以對接後面的計糧公式
        att_summary.rename(columns={'OT_Hours': 'OT Hours'}, inplace=True)

        # C. 將「精算後的工時」與「五大金剛微調」無縫合併
        att_df = pd.merge(att_summary, adj_df, on=['Name', 'Location'], how='left')
        att_df.fillna({'expenses': 0, 'adjustment': 0, 'attendance_bonus': 0}, inplace=True)
    else:
        # 防呆：如果該月完全沒有明細紀錄，就退回補零
        att_df = adj_df.copy() if not adj_df.empty else pd.DataFrame(columns=['Name', 'Location', 'Days', 'Hours', 'OT Hours', 'expenses', 'adjustment', 'attendance_bonus', 'basic_pay_override', 'allowance_override'])
        if not att_df.empty:
            att_df['Days'] = 0
            att_df['Hours'] = 0
            att_df['OT Hours'] = 0

    # 讀取銷售與特佣規則
    sales_df = pd.read_sql_query("SELECT promoter_name AS Name, location AS Location, model, quantity, price FROM Sales WHERE payroll_month = ?", conn, params=(calc_month,))
    prod_df = pd.read_sql_query("SELECT model, commission_rate AS prod_comm FROM Products", conn)
    spec_df = pd.read_sql_query("SELECT model, start_month, end_month, rate AS spec_comm FROM SpecialCommissions", conn)
    
    conn.close()

    # ==========================================
    # 2. 計算佣金 (三層優先級智能判定)
    # ==========================================
    if not sales_df.empty:
        sales_df = sales_df.merge(prod_df, on='model', how='left')
        spec_active = spec_df[(spec_df['start_month'] <= calc_month) & (spec_df['end_month'] >= calc_month)]
        spec_active = spec_active.drop_duplicates(subset=['model'], keep='last')
        sales_df = sales_df.merge(spec_active[['model', 'spec_comm']], on='model', how='left')
        sales_df = sales_df.merge(emp_df[['Name', 'default_comm']], on='Name', how='left')
        
        # 優先級：時段特佣 > 永久產品比例 > 員工預設比例 > 保底 0.03
        sales_df['applied_rate'] = sales_df['spec_comm'].combine_first(sales_df['prod_comm']).combine_first(sales_df['default_comm']).fillna(0.03)
        sales_df['Comm'] = sales_df['quantity'] * sales_df['price'] * sales_df['applied_rate']
        comm_summary = sales_df.groupby(['Name', 'Location'])['Comm'].sum().reset_index()
        comm_summary.rename(columns={'Comm': 'Calc_Comm'}, inplace=True)
    else:
        comm_summary = pd.DataFrame(columns=['Name', 'Location', 'Calc_Comm'])

    # ==========================================
    # 3. 數據安全合併 (🌟 關鍵修復：Outer Join 防漏算)
    # ==========================================
    if att_df.empty and comm_summary.empty:
        return []

    if not att_df.empty and not comm_summary.empty:
        # 使用 outer join，確保「只有打卡沒銷售」或「只有銷售沒打卡」的人都會被保留
        final_df = pd.merge(att_df, comm_summary, on=['Name', 'Location'], how='outer')
    elif not att_df.empty:
        final_df = att_df.copy()
        final_df['Calc_Comm'] = 0
    else:
        final_df = comm_summary.copy()
        for col in ['Days', 'Hours', 'OT Hours', 'expenses', 'adjustment', 'attendance_bonus', 'basic_pay_override', 'allowance_override']:
            final_df[col] = 0

    # 關聯員工時薪等基本資料
    final_df = final_df.merge(emp_df, on='Name', how='left')
    
    # 把空值補 0，防止數學計算報錯
    fill_zero_cols = ['Days', 'Hours', 'OT Hours', 'Calc_Comm', 'hourly_rate', 'allowance', 'expenses', 'adjustment', 'attendance_bonus']
    for col in fill_zero_cols:
        if col in final_df.columns:
            final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0)

    # ==========================================
    # 4. 智能彈性計算邏輯 (把微調金額加進去)
    # ==========================================
    def calc_basic(row):
        # 如果有人工覆寫底薪，強制使用覆寫值
        if 'basic_pay_override' in row and pd.notna(row['basic_pay_override']) and str(row['basic_pay_override']).strip() not in ['', '0', '0.0']:
            return float(row['basic_pay_override'])
        return (row['Hours'] + row['OT Hours']) * row['hourly_rate']
    
    def calc_allow(row):
        # 如果有人工覆寫津貼，強制使用覆寫值
        if 'allowance_override' in row and pd.notna(row['allowance_override']) and str(row['allowance_override']).strip() not in ['', '0', '0.0']:
            return float(row['allowance_override'])
        return row['Days'] * row['allowance']

    final_df['Basic Pay'] = final_df.apply(calc_basic, axis=1)
    final_df['Total_Allowance'] = final_df.apply(calc_allow, axis=1)
    
    # 💰 總收入 = 底薪 + 佣金 + 津貼 + 報銷(Expenses) + 微調(Adjustment) + 出勤獎(Attendance Bonus)
    final_df['Gross Pay'] = final_df['Basic Pay'] + final_df['Calc_Comm'] + final_df['Total_Allowance'] + final_df['expenses'] + final_df['adjustment'] + final_df['attendance_bonus']

    # ==========================================
    # 5. MPF 計算邏輯 (方案 B：精細化)
    # ==========================================
    def calc_mpf(row):
        mpf_amount = 0
        mpf_status = ""
        
        # 判斷是否為 MPF 計劃參與者
        if row.get('require_mpf', 1) == 1:
            start_month = row.get('mpf_start_month')
            
            # 判斷是否已過 60 天豁免期 (或未設定則預設已過)
            if pd.isna(start_month) or str(start_month).strip() == '' or calc_month >= str(start_month):
                if row['Gross Pay'] >= 7100:
                    # 符合扣除條件 (5%, 最高 $1500)
                    mpf_amount = min(row['Gross Pay'] * 0.05, 1500)
                    mpf_status = "已扣除 (5%)"
                else:
                    # 薪資低於下限，員工無需供款
                    mpf_status = "未達 $7,100 下限"
            else:
                # 仍在豁免期內
                mpf_status = f"🛡️ 豁免期 (起扣:{start_month})"
        else:
            # 永久免供款員工 (如大於 65 歲或特定合約)
            mpf_status = "🚫 永久豁免 (非 MPF 員工)"
            
        return pd.Series([mpf_amount, mpf_status])

    # 執行計算並拆分結果
    final_df[['MPF', 'MPF狀態']] = final_df.apply(calc_mpf, axis=1)
    final_df['Net Pay'] = final_df['Gross Pay'] - final_df['MPF']

    # ==========================================
    # 6. 整理最終輸出格式
    # ==========================================
    # 把新加入的微調欄位送到前端顯示
    display_df = final_df[['Name', 'full_name', 'Hours', 'OT Hours', 'Basic Pay', 'Calc_Comm', 'Total_Allowance', 'expenses', 'adjustment', 'attendance_bonus', 'Gross Pay', 'MPF', 'MPF狀態', 'Net Pay', 'Location']]
    display_df.columns = ['員工','全名', '工時', 'OT工時', '底薪', '總佣金', '津貼', '報銷', '微調', '出勤獎', '總收入', 'MPF扣除', 'MPF狀態', '實發薪資', '地點']

    numeric_cols = ['工時', 'OT工時', '底薪', '總佣金', '津貼', '報銷', '微調', '出勤獎', '總收入', 'MPF扣除', '實發薪資']
    display_df[numeric_cols] = display_df[numeric_cols].fillna(0).round(2)

    return display_df.to_dict('records')