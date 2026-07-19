"""API 回傳資料 → payroll SQLite 表格的格式轉換。

外部 API 的欄位名稱可能與 payroll 系統不同，
此模組負責將 API 回傳的原始 JSON 轉換為
importer.py 可直接寫入資料庫的 dict 格式。
"""


# ── 銷售報表轉換 ──────────────────────────────────────────────────────

def transform_sales_report(api_rows, brand_code, payroll_month):
    """將 API /report/sale 回傳資料轉為 Sales 表格式。

    外部 API 預期欄位：
        account      → promoter_name （推銷員帳號）
        headerID     → （略，供 API 操作使用）
        productName  → model （產品型號）
        date / Date  → date （銷售日期）
        qty          → quantity
        price        → price
        shop / Shop  → location（店舖）

    Returns:
        list[dict]: 可直接用於 INSERT INTO Sales 的資料列
    """
    sales = []
    for row in api_rows:
        if not isinstance(row, dict):
            continue
        promoter = str(row.get("account", "") or row.get("promoter", "") or row.get("Promoter", "") or row.get("Name", "")).strip()
        model = str(row.get("productName", "") or row.get("model", "") or row.get("Model", "") or row.get("Item", "")).strip()
        if not promoter or not model:
            continue

        qty = _safe_int(row.get("qty") or row.get("Qty") or row.get("quantity") or row.get("Quantity") or 1)
        price = _safe_float(row.get("price") or row.get("Price") or 0)
        sale_date = str(row.get("date", "") or row.get("Date", "") or "")
        shop = str(row.get("shop", "") or row.get("Shop", "") or row.get("Store", "") or "")
        location = str(row.get("location", "") or row.get("Location", "") or row.get("Area", "") or "")
        loc = f"{shop} {location}".strip() if location else shop

        sales.append({
            "brand_code": brand_code,
            "payroll_month": payroll_month,
            "date": sale_date,
            "promoter_name": promoter,
            "location": loc,
            "model": model,
            "quantity": qty,
            "price": price,
        })
    return sales


# ── 出勤報表轉換 ──────────────────────────────────────────────────────

def transform_duty_report(api_rows, brand_code, payroll_month):
    """將 API /report/duty 回傳資料轉為 DailyAttendance 與 Attendance 格式。

    外部 API 預期欄位：
        account      → nick_name
        date         → work_date
        shop         → location
        hours        → actual_hours
        normal_hours → normal_hours（若無則用 hours）
        ot_hours     → ot_hours

    Returns:
        (daily_rows, attendance_totals)
        - daily_rows: list[dict] 每日打卡明細
        - attendance_totals: dict[(nick_name, loc), {days, hours, ot}]
    """
    daily_rows = []
    attendance_totals = {}

    for row in api_rows:
        if not isinstance(row, dict):
            continue
        nick_name = str(row.get("account", "") or row.get("Account", "") or row.get("name", "") or row.get("Name", "")).strip()
        if not nick_name or nick_name.lower() in {"nan", "0", ""}:
            continue

        work_date = str(row.get("date", "") or row.get("Date", "") or "")
        loc = str(row.get("shop", "") or row.get("Shop", "") or row.get("location", "") or row.get("Location", "") or "").strip()

        actual_h = _safe_float(row.get("hours") or row.get("Hours") or row.get("actual_hours") or row.get("Actual Hours") or 0)
        normal_h = _safe_float(row.get("normal_hours") or row.get("Normal Hours") or actual_h)
        raw_ot = _safe_float(row.get("ot_hours") or row.get("OT Hours") or row.get("Overtime") or 0)

        # OT 半小時進位（與 Excel 匯入規則一致）
        clean_ot = 0.0
        if raw_ot >= 0.5:
            import math
            clean_ot = math.floor(raw_ot / 0.5) * 0.5

        daily_rows.append({
            "brand_code": brand_code,
            "payroll_month": payroll_month,
            "work_date": work_date,
            "nick_name": nick_name,
            "location": loc,
            "normal_hours": normal_h,
            "actual_hours": actual_h,
            "ot_hours": clean_ot,
        })

        key = (nick_name, loc)
        if key not in attendance_totals:
            attendance_totals[key] = {"days": 0, "hours": 0.0, "ot": 0.0}
        attendance_totals[key]["days"] += 1
        # payable_normal = actual_h - raw_ot（與 process_excel_import 邏輯一致）
        payable_hours = actual_h - raw_ot
        if payable_hours < 0:
            payable_hours = 0
        attendance_totals[key]["hours"] += payable_hours
        attendance_totals[key]["ot"] += clean_ot

    return daily_rows, attendance_totals


# ── 員工資料轉換 ──────────────────────────────────────────────────────

def transform_profile_report(api_rows, brand_code):
    """將 API /report/profile 回傳資料轉為 Employees 與 MonthlyRates 格式。

    外部 API 預期欄位：
        account      → nick_name
        fullName     → full_name
        hourlyRate   → hourly_rate
        allowance    → allowance
        commissionRate → commission_rate
        salaryType   → salary_type（hourly / monthly）
        monthlySalary → monthly_salary

    Returns:
        list[dict]: 可用於 INSERT INTO Employees 的資料列
    """
    employees = []
    for row in api_rows:
        if not isinstance(row, dict):
            continue
        nick_name = str(row.get("account", "") or row.get("Account", "") or row.get("name", "") or row.get("Name", "")).strip()
        if not nick_name or nick_name.lower() in {"nan", "0", ""}:
            continue

        employees.append({
            "brand_code": brand_code,
            "nick_name": nick_name,
            "full_name": str(row.get("fullName", "") or row.get("FullName", "") or row.get("full_name", "") or "").strip(),
            "hourly_rate": _safe_float(row.get("hourlyRate") or row.get("HourlyRate") or row.get("hourly_rate") or 0),
            "allowance": _safe_float(row.get("allowance") or row.get("Allowance") or 0),
            "commission_rate": _parse_commission_rate(row.get("commissionRate") or row.get("CommissionRate") or row.get("commission_rate") or 0),
            "salary_type": str(row.get("salaryType") or row.get("SalaryType") or row.get("salary_type") or "hourly").strip().lower(),
            "monthly_salary": _safe_float(row.get("monthlySalary") or row.get("MonthlySalary") or row.get("monthly_salary") or 0),
        })
    return employees


# ── 輔助函數 ──────────────────────────────────────────────────────────

def _safe_int(value):
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return 1


def _safe_float(value):
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return 0.0


def _parse_commission_rate(value):
    """將佣金率轉為小數格式（3 → 0.03, 0.03 → 0.03）。"""
    try:
        v = float(str(value).strip().replace("%", ""))
        return v / 100.0 if v > 1 else v
    except (ValueError, TypeError):
        return 0.02
