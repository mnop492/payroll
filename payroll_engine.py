import sqlite3
import pandas as pd
import math  # 🌟 新增：用於精準計算 OT 進位

def process_payroll_from_db(calc_month, brand_code='century_field', db_path='payroll.db'):
    """
    安全升級版計糧大腦：支援五大彈性微調，並保證不漏算任何員工
    """
    conn = sqlite3.connect(db_path)
    
    # ==========================================
    # 1. 讀取所需資料庫
    # ==========================================
    emp_df = pd.read_sql_query(
        """
        SELECT e.nick_name AS Name,
               e.hourly_rate AS hourly_rate,
               e.salary_type AS salary_type,         -- ✅ 新增
               e.monthly_salary AS monthly_salary,   -- ✅ 新增
               mr.hourly_rate AS monthly_hourly_rate,
               mr.commission_rate AS monthly_comm,
               mr.monthly_salary AS monthly_salary_override,
               e.allowance,
               e.commission_rate AS default_comm,
               e.require_mpf,
               e.mpf_start_month,
               e.full_name
        FROM Employees e
        LEFT JOIN MonthlyRates mr ON mr.nick_name = e.nick_name AND mr.payroll_month = ? AND mr.brand_code = ?
        WHERE e.brand_code = ?
        """,
        conn,
        params=(calc_month, brand_code, brand_code)
    )
    
    # ==========================================
    # 2. 讀取考勤與每日明細 (🌟 升級版每日 OT 結算)
    # ==========================================
    # A. 先讀取「每日打卡明細」
    daily_df = pd.read_sql_query("""
        SELECT nick_name AS Name, location AS Location, work_date, actual_hours, normal_hours, ot_hours AS raw_ot
        FROM DailyAttendance 
        WHERE brand_code = ? AND payroll_month = ?
    """, conn, params=(brand_code, calc_month))

    # B. 讀取原本 Attendance 表中的「五大金剛微調」與「津貼」
    adj_df = pd.read_sql_query("""
        SELECT nick_name AS Name, location AS Location, 
               expenses, adjustment, attendance_bonus, basic_pay_override, allowance_override 
        FROM Attendance WHERE brand_code = ? AND payroll_month = ?
    """, conn, params=(brand_code, calc_month))

    if not daily_df.empty:
       # 🌟 核心 OT 規則：不足半小時不計，每半小時跳一級 (新增支援負數扣鐘)
        def apply_clean_ot(raw_ot):
            if pd.isna(raw_ot):
                return 0.0
            
            # ✅ 小於半小時（含接近 0 的負浮點誤差）一律視為 0
            if -0.5 < raw_ot < 0.5:
                return 0.0

            # ✅ 處理負數 (扣鐘/遲到/早退)：以 0.5 為單位向下進位 (保留原始扣除量)
            if raw_ot <= -0.5:
                return math.floor(raw_ot * 2) / 2.0

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
        att_df = att_df.fillna({'expenses': 0, 'adjustment': 0, 'attendance_bonus': 0})
    else:
        # 防呆：如果該月完全沒有明細紀錄，就退回補零
        att_df = adj_df.copy() if not adj_df.empty else pd.DataFrame(columns=['Name', 'Location', 'Days', 'Hours', 'OT Hours', 'expenses', 'adjustment', 'attendance_bonus', 'basic_pay_override', 'allowance_override'])
        if not att_df.empty:
            att_df['Days'] = 0
            att_df['Hours'] = 0
            att_df['OT Hours'] = 0

    # 讀取銷售與特佣規則
    sales_df = pd.read_sql_query("SELECT promoter_name AS Name, location AS Location, date, model, quantity, price FROM Sales WHERE brand_code = ? AND payroll_month = ?", conn, params=(brand_code, calc_month))
    prod_df = pd.read_sql_query(
        "SELECT model, commission_rate AS prod_comm FROM Products WHERE brand_code = ?",
        conn,
        params=(brand_code,),
    )
    spec_df = pd.read_sql_query(
        "SELECT model, start_month, end_month, rate AS spec_comm FROM SpecialCommissions WHERE brand_code = ?",
        conn,
        params=(brand_code,),
    )

    # 正規化 sales_df 欄位：date 格式化為 YYYY-MM-DD；quantity, price 轉為數值
    if not sales_df.empty:
        # 轉為 datetime，再格式化為與 DailyAttendance.work_date 相同的字串格式
        sales_df['date'] = pd.to_datetime(sales_df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
        # 若某些日期解析失敗，保留原字串（避免全部變成 NaN 而丟失資料）
        sales_df['date'] = sales_df['date'].fillna(sales_df['date'].astype(str))
        sales_df['quantity'] = pd.to_numeric(sales_df.get('quantity', 0), errors='coerce').fillna(0)
        sales_df['price'] = pd.to_numeric(sales_df.get('price', 0), errors='coerce').fillna(0.0)

    conn.close()

    # ==========================================
    # 2. 計算佣金 (同一店鋪同一日平均分配)
    # ==========================================
    if not sales_df.empty:
        sales_df = sales_df.merge(prod_df, on='model', how='left')
        spec_active = spec_df[(spec_df['start_month'] <= calc_month) & (spec_df['end_month'] >= calc_month)]
        spec_active = spec_active.drop_duplicates(subset=['model'], keep='last')
        sales_df = sales_df.merge(spec_active[['model', 'spec_comm']], on='model', how='left')
        
        # 🌟 改變 1：把 monthly_comm 也一起從員工資料表 (emp_df) 裡拿過來
        sales_df = sales_df.merge(emp_df[['Name', 'default_comm', 'monthly_comm']], on='Name', how='left')
        
        # 先將佣金比例轉成數值，避免 combine_first 造成 dtype warning
        # 🌟 改變 2：將 monthly_comm 加入數字轉換的陣列中，防止報錯
        for col in ['spec_comm', 'prod_comm', 'monthly_comm', 'default_comm']:
            if col in sales_df.columns:
                sales_df[col] = pd.to_numeric(sales_df[col], errors='coerce')

        # 🌟 改變 3：更新佣金優先級公式！
        # 順序變成：時段特佣 > 產品特佣 > 【本月覆寫佣金】 > 員工預設佣金 > 保底 0.03
        sales_df['applied_rate'] = sales_df['spec_comm'].fillna(sales_df['prod_comm']).fillna(sales_df['monthly_comm']).fillna(sales_df['default_comm']).fillna(0.03)
        
        sales_df['Comm'] = sales_df['quantity'] * sales_df['price'] * sales_df['applied_rate']        
        # 先算出每個日期+店鋪的總佣金
        daily_comm = sales_df.groupby(['date', 'Location'])['Comm'].sum().reset_index(name='Total_Comm')

        # 計算同一日期同一店鋪的出勤人數，用以平均分配佣金
        worker_days = daily_df[['work_date', 'Name', 'Location']].drop_duplicates()
        worker_count = worker_days.groupby(['work_date', 'Location'])['Name'].nunique().reset_index(name='worker_count')
        worker_count.rename(columns={'work_date': 'date'}, inplace=True)

        # 平均分配給當日當店的每位員工
        daily_comm = daily_comm.merge(worker_count, on=['date', 'Location'], how='left')
        daily_comm['worker_count'] = daily_comm['worker_count'].fillna(1).replace(0, 1)
        daily_comm['share_per_person'] = daily_comm['Total_Comm'] / daily_comm['worker_count']

        # 每位員工每個出勤日分得一份
        daily_shares = worker_days.rename(columns={'work_date': 'date'}).merge(
            daily_comm[['date', 'Location', 'share_per_person']], on=['date', 'Location'], how='left'
        )
        daily_shares['share_per_person'] = daily_shares['share_per_person'].fillna(0)

        comm_summary = daily_shares.groupby(['Name', 'Location'])['share_per_person'].sum().reset_index(name='Calc_Comm')
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

    # 月薪制同事：同月份跨多店只計一次月薪/津貼（其餘店鋪列為 0）
    if not final_df.empty:
        if 'Location' in final_df.columns:
            final_df['Location'] = final_df['Location'].fillna('')
            final_df = final_df.sort_values(['Name', 'Location'], kind='stable').reset_index(drop=True)
        final_df['_monthly_seq'] = 0
        monthly_mask = final_df['salary_type'].eq('monthly') if 'salary_type' in final_df.columns else pd.Series(False, index=final_df.index)
        if monthly_mask.any():
            final_df.loc[monthly_mask, '_monthly_seq'] = (
                final_df.loc[monthly_mask].groupby('Name').cumcount()
            )

    monthly_allow_override_map = {}
    if 'allowance_override' in final_df.columns and 'salary_type' in final_df.columns:
        monthly_rows = final_df[final_df['salary_type'].eq('monthly')]
        for name, grp in monthly_rows.groupby('Name'):
            override_vals = [
                float(v)
                for v in grp['allowance_override']
                if pd.notna(v) and str(v).strip() not in ['', '0', '0.0']
            ]
            if override_vals:
                monthly_allow_override_map[name] = override_vals[0]
    
    
    # 如果有月度覆寫時薪，優先使用；否則使用員工預設時薪
    if 'monthly_hourly_rate' in final_df.columns:
        final_df['hourly_rate'] = final_df['monthly_hourly_rate'].fillna(final_df['hourly_rate'])

    # 把空值補 0，防止數學計算報錯
    fill_zero_cols = ['Days', 'Hours', 'OT Hours', 'Calc_Comm', 'hourly_rate', 'allowance', 'expenses', 'adjustment', 'attendance_bonus']
    for col in fill_zero_cols:
        if col in final_df.columns:
            final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0)

    # ==========================================
    # 4. 智能彈性計算邏輯 (把微調金額加進去)
    # ==========================================
    def calculate_basic_pay(row):
        # 如果是月薪制，優先使用本月專屬月薪，否則使用預設月薪
        if row.get('salary_type') == 'monthly':
            # 跨多店只計一次月薪，其餘店鋪歸零
            if row.get('_monthly_seq', 0) > 0:
                return 0
            # 優先抓取 MonthlyRates 的 Override
            override_salary = row.get('monthly_salary_override')
            return override_salary if pd.notna(override_salary) else row.get('monthly_salary', 0)

        # 否則維持原來的時薪計算邏輯
        effective_hr = row.get('monthly_hourly_rate') if pd.notna(row.get('monthly_hourly_rate')) else row.get('hourly_rate', 0)
        return row.get('hours', 0) * effective_hr

    # 應用公式計算底薪 (注意：依據你原本的 DataFrame 欄位名稱可能是 'hours' 或 'Reg.Hrs')
    final_df['底薪'] = final_df.apply(calculate_basic_pay, axis=1)
    
    def calc_allow(row):
        # 如果有人工覆寫津貼，強制使用覆寫值
        if 'allowance_override' in row and pd.notna(row['allowance_override']) and str(row['allowance_override']).strip() not in ['', '0', '0.0']:
            return float(row['allowance_override'])
        # 月薪制：津貼視為一筆過，不按日數計算；跨多店只計一次
        if row.get('salary_type') == 'monthly':
            if row.get('_monthly_seq', 0) > 0:
                return 0
            return row.get('allowance', 0)
        return row['Days'] * row['allowance']

    final_df['Basic Pay'] = final_df.apply(calculate_basic_pay, axis=1)
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
    display_df = final_df[['Name', 'full_name', 'salary_type', '_monthly_seq', 'Hours', 'OT Hours', 'Basic Pay', 'Calc_Comm', 'Total_Allowance', 'expenses', 'adjustment', 'attendance_bonus', 'Gross Pay', 'MPF', 'MPF狀態', 'Net Pay', 'Location']].copy()

    # 🌟 月薪制：合併跨多店的記錄，只輸出一條
    if not display_df.empty and 'salary_type' in display_df.columns:
        monthly_mask = display_df['salary_type'].eq('monthly')
        if monthly_mask.any():
            monthly_df = display_df[monthly_mask]
            # 建立地點對照：每個員工的所有地點串聯
            loc_map = monthly_df.groupby('Name')['Location'].apply(
                lambda x: '、'.join(x.dropna().replace('', pd.NA).dropna().unique())
            )
            # 只保留每個員工的第一筆 (_monthly_seq == 0)，並更新地點
            monthly_merged = monthly_df[monthly_df['_monthly_seq'] == 0].copy()
            monthly_merged['Location'] = monthly_merged['Name'].map(loc_map).fillna(monthly_merged['Location'])
            # 合併時薪制與月薪制
            display_df = pd.concat([display_df[~monthly_mask], monthly_merged], ignore_index=True)

    # 只保留需要的欄位輸出
    display_df = display_df[['Name', 'full_name', 'salary_type', 'Hours', 'OT Hours', 'Basic Pay', 'Calc_Comm', 'Total_Allowance', 'expenses', 'adjustment', 'attendance_bonus', 'Gross Pay', 'MPF', 'MPF狀態', 'Net Pay', 'Location']]
    display_df.columns = ['員工','全名', 'salary_type', '工時', 'OT工時', '底薪', '總佣金', '津貼', '報銷', '微調', '出勤獎', '總收入', 'MPF扣除', 'MPF狀態', '實發薪資', '地點']

    numeric_cols = ['工時', 'OT工時', '底薪', '總佣金', '津貼', '報銷', '微調', '出勤獎', '總收入', 'MPF扣除', '實發薪資']
    display_df[numeric_cols] = display_df[numeric_cols].fillna(0).round(2)

    return display_df.to_dict('records')