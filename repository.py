import os
import sqlite3

from app_config import DB_PATH, HISTORY_FOLDER


def get_db_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_audit_table():
    conn = get_db_connection()
    conn.execute(
        """
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
        """
    )
    conn.commit()
    conn.close()


def ensure_monthly_rates_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS MonthlyRates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payroll_month TEXT NOT NULL,
            nick_name TEXT NOT NULL,
            hourly_rate REAL,
            allowance REAL,
            commission_rate REAL,
            UNIQUE(payroll_month, nick_name)
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_users_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS Users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_login_attempts_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS LoginAttempts (
            username TEXT NOT NULL,
            ip TEXT NOT NULL,
            failed_count INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, ip)
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_month_input_source_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS MonthInputSource (
            payroll_month TEXT PRIMARY KEY,
            input_source TEXT NOT NULL CHECK (input_source IN ('excel', 'web')),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_core_tables():
    ensure_audit_table()
    ensure_monthly_rates_table()
    ensure_users_table()
    ensure_login_attempts_table()
    ensure_month_input_source_table()


def set_month_input_source(payroll_month, input_source):
    if not payroll_month or input_source not in {"excel", "web"}:
        return

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO MonthInputSource (payroll_month, input_source)
        VALUES (?, ?)
        ON CONFLICT(payroll_month) DO UPDATE SET
            input_source = excluded.input_source,
            updated_at = CURRENT_TIMESTAMP
        """,
        (payroll_month, input_source),
    )
    conn.commit()
    conn.close()


def get_month_input_source(payroll_month):
    if not payroll_month:
        return None

    conn = get_db_connection()
    row = conn.execute(
        "SELECT input_source FROM MonthInputSource WHERE payroll_month = ?",
        (payroll_month,),
    ).fetchone()
    conn.close()
    return row["input_source"] if row else None


def month_has_excel_history(payroll_month):
    if not payroll_month:
        return False
    if not os.path.isdir(HISTORY_FOLDER):
        return False

    month_key = payroll_month.replace("-", "")
    for filename in os.listdir(HISTORY_FOLDER):
        if not filename.endswith(".xlsx") or filename.startswith("~"):
            continue
        if filename.startswith(month_key):
            return True
    return False


def sync_attendance_summary(month, nick_name, location):
    conn = get_db_connection()
    summary = conn.execute(
        """
        SELECT
            COUNT(work_date) AS t_days,
            SUM(actual_hours - ot_hours) AS t_hours,
            SUM(ot_hours) AS t_ot
        FROM DailyAttendance
        WHERE payroll_month = ? AND nick_name = ? AND location = ?
        """,
        (month, nick_name, location),
    ).fetchone()

    days = summary["t_days"] or 0
    hours = summary["t_hours"] or 0.0
    ot = summary["t_ot"] or 0.0

    conn.execute(
        """
        INSERT OR IGNORE INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours)
        VALUES (?, ?, ?, 0, 0, 0)
        """,
        (month, nick_name, location),
    )
    conn.execute(
        """
        UPDATE Attendance
        SET days_worked = ?, hours = ?, ot_hours = ?
        WHERE payroll_month = ? AND nick_name = ? AND location = ?
        """,
        (days, hours, ot, month, nick_name, location),
    )
    conn.commit()
    conn.close()


def fetch_index_context(current_month, payroll_results):
    conn = get_db_connection()
    records = conn.execute("SELECT * FROM Sales WHERE payroll_month = ?", (current_month,)).fetchall()
    attendances_raw = conn.execute("SELECT * FROM Attendance WHERE payroll_month = ?", (current_month,)).fetchall()
    staff_summary_raw = conn.execute(
        """
        SELECT promoter_name AS name, location AS main_location,
               COUNT(*) AS total_entries, SUM(quantity * price) AS total_amount
        FROM Sales WHERE payroll_month = ?
        GROUP BY promoter_name, location ORDER BY name, total_amount DESC
        """,
        (current_month,),
    ).fetchall()
    locations = conn.execute("SELECT name FROM Locations ORDER BY name").fetchall()
    products = conn.execute("SELECT model FROM Products ORDER BY model").fetchall()
    employees_rows = conn.execute(
        "SELECT nick_name, full_name, hourly_rate, commission_rate FROM Employees ORDER BY nick_name"
    ).fetchall()
    monthly_rates_rows = conn.execute(
        "SELECT nick_name, hourly_rate, commission_rate FROM MonthlyRates WHERE payroll_month = ?",
        (current_month,),
    ).fetchall()
    conn.close()

    month_input_source = get_month_input_source(current_month)
    has_excel_history = month_has_excel_history(current_month)

    attendances = []
    for row in attendances_raw:
        record = dict(row)
        for field in ["hours", "days_worked", "ot_hours", "expenses", "adjustment", "attendance_bonus"]:
            if record.get(field) is None:
                record[field] = 0
        if record.get("basic_pay_override") is None:
            record["basic_pay_override"] = ""
        if record.get("allowance_override") is None:
            record["allowance_override"] = ""
        attendances.append(record)

    commission_map = {(row["員工"], row["地點"]): float(row["總佣金"]) for row in payroll_results}
    staff_summary = []
    for row in staff_summary_raw:
        record = dict(row)
        record["total_amount"] = float(record["total_amount"] or 0)
        record["total_comm"] = commission_map.get((record["name"], record["main_location"]), 0.0)
        staff_summary.append(record)

    monthly_rate_map = {
        row["nick_name"]: float(row["hourly_rate"]) if row["hourly_rate"] is not None else None
        for row in monthly_rates_rows
    }
    monthly_comm_map = {
        row["nick_name"]: float(row["commission_rate"]) if row["commission_rate"] is not None else None
        for row in monthly_rates_rows
    }
    emp_full_map = {row["nick_name"]: (row["full_name"] or "") for row in employees_rows}
    emp_default_hr_map = {row["nick_name"]: float(row["hourly_rate"] or 0) for row in employees_rows}
    emp_default_comm_map = {
        row["nick_name"]: float(row["commission_rate"] or 0.03) for row in employees_rows
    }

    for attendance in attendances:
        attendance["full_name"] = emp_full_map.get(attendance.get("nick_name"), "")
        attendance["monthly_hourly_rate"] = monthly_rate_map.get(attendance.get("nick_name"))
        attendance["default_hourly_rate"] = emp_default_hr_map.get(attendance.get("nick_name"), 0)

    for summary in staff_summary:
        summary["full_name"] = emp_full_map.get(summary.get("name"), "")
        summary["monthly_hourly_rate"] = monthly_rate_map.get(summary.get("name"))
        summary["monthly_comm"] = monthly_comm_map.get(summary.get("name"))
        summary["default_comm"] = emp_default_comm_map.get(summary.get("name"), 0.03)

    if not month_input_source and has_excel_history:
        month_input_source = "excel"
    if not month_input_source and (attendances or staff_summary):
        month_input_source = "web"

    return {
        "records": records,
        "attendances": attendances,
        "staff_summary": staff_summary,
        "locations": locations,
        "products": products,
        "employees": employees_rows,
        "month_input_source": month_input_source,
        "has_excel_history": has_excel_history,
    }


def fetch_settings_context(current_month):
    conn = get_db_connection()
    employees = conn.execute("SELECT * FROM Employees ORDER BY nick_name").fetchall()
    monthly_rates = conn.execute(
        "SELECT nick_name, hourly_rate, commission_rate FROM MonthlyRates WHERE payroll_month = ?",
        (current_month,),
    ).fetchall()
    conn.close()
    monthly_map = {row["nick_name"]: row["hourly_rate"] for row in monthly_rates}
    monthly_comm_map = {row["nick_name"]: row["commission_rate"] for row in monthly_rates}
    return employees, monthly_map, monthly_comm_map


def fetch_manage_products_context():
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM Products ORDER BY model").fetchall()
    special_rules = conn.execute("SELECT * FROM SpecialCommissions ORDER BY start_month DESC").fetchall()
    conn.close()
    return products, special_rules


def fetch_manage_locations_context():
    conn = get_db_connection()
    locations = conn.execute("SELECT * FROM Locations ORDER BY region, name").fetchall()
    conn.close()
    return locations


def fetch_daily_attendance(month, nick_name, location):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, work_date, in_time, out_time, normal_hours, actual_hours, ot_hours, location
        FROM DailyAttendance
        WHERE payroll_month = ? AND nick_name = ? AND location = ?
        ORDER BY work_date
        """,
        (month, nick_name, location),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_sales_records(month, nick_name, location):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, date, location, model, quantity, price
        FROM Sales
        WHERE payroll_month = ? AND promoter_name = ? AND location = ?
        ORDER BY date
        """,
        (month, nick_name, location),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
