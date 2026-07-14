import copy
import json
import logging
import os
from functools import wraps
from datetime import datetime, timedelta

import pandas as pd
from flask import flash, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app_config import (
    ADMIN_USERS,
    AUDIT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    HISTORY_FOLDER,
    LOGIN_LOCK_MINUTES,
    MAX_LOGIN_ATTEMPTS,
)
from repository import get_db_connection
from payroll_engine import process_payroll_from_db


def is_audit_admin():
    return bool(session.get("is_admin")) or session.get("user") in ADMIN_USERS


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("user"):
            flash("請先登入後再使用系統。", "warning")
            return redirect(url_for("main.login", next=request.url))
        return view_func(*args, **kwargs)

    return wrapped_view


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("user"):
            flash("請先登入後再使用系統。", "warning")
            return redirect(url_for("main.login", next=request.url))
        if not session.get("is_admin"):
            flash("需要管理員權限。", "warning")
            return redirect(url_for("main.index"))
        return view_func(*args, **kwargs)

    return wrapped_view


def seed_default_admin_user():
    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM Users WHERE username = ?", (DEFAULT_ADMIN_USERNAME,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO Users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            (DEFAULT_ADMIN_USERNAME, generate_password_hash(AUDIT_ADMIN_PASSWORD)),
        )
        conn.commit()
    conn.close()


def authenticate_user(username, password):
    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, username, password_hash, is_admin, is_active FROM Users WHERE username = ?",
        (username,),
    ).fetchone()

    if user and user["is_active"] and check_password_hash(user["password_hash"], password):
        conn.close()
        return dict(user)

    # Self-heal path: allow env admin credential to recover a mismatched default admin password.
    if username == DEFAULT_ADMIN_USERNAME and password == AUDIT_ADMIN_PASSWORD:
        password_hash = generate_password_hash(AUDIT_ADMIN_PASSWORD)
        if user:
            conn.execute(
                "UPDATE Users SET password_hash = ?, is_admin = 1, is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                (password_hash, username),
            )
        else:
            conn.execute(
                "INSERT INTO Users (username, password_hash, is_admin, is_active) VALUES (?, ?, 1, 1)",
                (username, password_hash),
            )
        conn.commit()
        repaired_user = conn.execute(
            "SELECT id, username, password_hash, is_admin, is_active FROM Users WHERE username = ?",
            (username,),
        ).fetchone()
        conn.close()
        return dict(repaired_user) if repaired_user else None

    conn.close()
    return None


def _utc_now():
    return datetime.utcnow()


def _parse_utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def check_login_allowed(username, ip):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT failed_count, locked_until FROM LoginAttempts WHERE username = ? AND ip = ?",
        (username, ip),
    ).fetchone()
    conn.close()
    if not row:
        return True, 0
    locked_until = _parse_utc(row["locked_until"])
    if locked_until and locked_until > _utc_now():
        return False, max(1, int((locked_until - _utc_now()).total_seconds()))
    return True, 0


def record_login_failure(username, ip):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT failed_count, locked_until FROM LoginAttempts WHERE username = ? AND ip = ?",
        (username, ip),
    ).fetchone()

    failed_count = 1
    locked_until = None
    if row:
        prev_locked_until = _parse_utc(row["locked_until"])
        if prev_locked_until and prev_locked_until > _utc_now():
            failed_count = MAX_LOGIN_ATTEMPTS
        else:
            failed_count = int(row["failed_count"] or 0) + 1

    if failed_count >= MAX_LOGIN_ATTEMPTS:
        locked_until = (_utc_now() + timedelta(minutes=LOGIN_LOCK_MINUTES)).isoformat()

    conn.execute(
        """
        INSERT INTO LoginAttempts (username, ip, failed_count, locked_until, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(username, ip) DO UPDATE SET
            failed_count = excluded.failed_count,
            locked_until = excluded.locked_until,
            updated_at = CURRENT_TIMESTAMP
        """,
        (username, ip, failed_count, locked_until),
    )
    conn.commit()
    conn.close()

    if locked_until:
        return True, LOGIN_LOCK_MINUTES * 60
    return False, 0


def clear_login_failures(username, ip):
    conn = get_db_connection()
    conn.execute("DELETE FROM LoginAttempts WHERE username = ? AND ip = ?", (username, ip))
    conn.commit()
    conn.close()


def get_request_ip():
    try:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    except Exception:
        pass
    return request.remote_addr or "unknown"


def _redact_sensitive(data):
    if data is None:
        return None
    if isinstance(data, list):
        return [_redact_sensitive(item) for item in data]
    if isinstance(data, dict):
        redacted = copy.deepcopy(data)
        for key in list(redacted.keys()):
            lowered = str(key).lower()
            if lowered in {"password", "password_hash", "new_password"}:
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = _redact_sensitive(redacted[key])
        return redacted
    return data


def log_audit(action, table_name, record_id=None, old_value=None, new_value=None, user=None, ip=None):
    try:
        timestamp = datetime.utcnow().isoformat()
        if not user:
            try:
                user = session.get("user")
            except Exception:
                user = None
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO AuditLog (timestamp, user, action, table_name, record_id, old_value, new_value, ip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                user,
                action,
                table_name,
                str(record_id) if record_id is not None else None,
                json.dumps(_redact_sensitive(old_value), ensure_ascii=False) if old_value is not None else None,
                json.dumps(_redact_sensitive(new_value), ensure_ascii=False) if new_value is not None else None,
                ip,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logging.exception("Failed to write audit log: %s", exc)


def perform_validation(payroll_month_filter=None):
    validation_results = []
    if not os.path.exists(HISTORY_FOLDER):
        return []

    for filename in sorted(os.listdir(HISTORY_FOLDER)):
        if not filename.endswith(".xlsx") or filename.startswith("~"):
            continue

        month_str = filename[:6]
        payroll_month = f"{month_str[:4]}-{month_str[4:]}"
        if payroll_month_filter and payroll_month != payroll_month_filter:
            continue
        sys_records = process_payroll_from_db(payroll_month)
        if not sys_records:
            continue

        # Fetch extra DB detail for this month (attendance, sales, rates)
        conn = get_db_connection()
        att_rows = conn.execute(
            """SELECT nick_name, location, days_worked, hours, ot_hours,
                      expenses, adjustment, attendance_bonus
               FROM Attendance WHERE payroll_month = ?""",
            (payroll_month,),
        ).fetchall()
        att_map = {(r["nick_name"], r["location"]): dict(r) for r in att_rows}

        sales_rows = conn.execute(
            """SELECT promoter_name, location,
                      COUNT(*) AS entries,
                      SUM(quantity * price) AS amount
               FROM Sales WHERE payroll_month = ?
               GROUP BY promoter_name, location""",
            (payroll_month,),
        ).fetchall()
        sales_map = {(r["promoter_name"], r["location"]): dict(r) for r in sales_rows}

        emp_rows = conn.execute(
            """SELECT e.nick_name,
                      e.hourly_rate  AS default_hr,
                      e.commission_rate AS default_comm,
                      mr.hourly_rate AS monthly_hr,
                      mr.commission_rate AS monthly_comm
               FROM Employees e
               LEFT JOIN MonthlyRates mr
                      ON mr.nick_name = e.nick_name AND mr.payroll_month = ?""",
            (payroll_month,),
        ).fetchall()
        emp_map = {r["nick_name"]: dict(r) for r in emp_rows}
        conn.close()

        try:
            filepath = os.path.join(HISTORY_FOLDER, filename)
            ex_df = pd.read_excel(filepath, sheet_name="Total", header=6)
            ex_df.columns = ex_df.columns.astype(str).str.strip()
            ex_df = ex_df.dropna(subset=["Name", "Total"])
        except Exception as exc:
            logging.exception("Failed to read validation file %s", filepath)
            continue

        # Read attendance sheet to get Excel-side hours per person+location
        ex_hours_map = {}
        try:
            ts_df = pd.read_excel(filepath, sheet_name="工作表1", header=1)
            ts_df.columns = ts_df.columns.astype(str).str.strip()
            for _, tr in ts_df.iterrows():
                nn = str(tr.get("Nick Name", "")).strip()
                if not nn or nn.lower() == "nan":
                    continue
                tl = str(tr.get("Location", "")).strip()
                actual_h = float(pd.to_numeric(tr.get(" Hours", tr.get("Hours", tr.get("Hours Worked", 0))), errors="coerce") or 0)
                raw_ot = float(pd.to_numeric(tr.get("OT Hours", tr.get("OT hours", 0)), errors="coerce") or 0)
                import math as _math

                # Align with payroll_engine OT cleaning logic, including negative OT.
                # Values between -0.5 and 0.5 are treated as zero to avoid tiny float noise.
                if -0.5 < raw_ot < 0.5:
                    clean_ot = 0.0
                elif raw_ot <= -0.5:
                    clean_ot = _math.floor(raw_ot * 2) / 2.0
                else:
                    clean_ot = _math.floor(raw_ot / 0.5) * 0.5

                payable = actual_h - raw_ot
                key = (nn, tl)
                if key not in ex_hours_map:
                    ex_hours_map[key] = {"days": 0, "hours": 0.0, "ot": 0.0}
                ex_hours_map[key]["days"] += 1
                ex_hours_map[key]["hours"] += payable
                ex_hours_map[key]["ot"] += clean_ot
        except Exception:
            pass  # sheet may not exist; ex hours stay at 0

        for _, ex_row in ex_df.iterrows():
            name = str(ex_row["Name"]).strip()
            loc = str(ex_row.get("Shop", "")).strip()

            def _safe(val, default=0):
                try:
                    v = float(val)
                    return v if not (v != v) else default  # NaN check
                except Exception:
                    return default

            ex_vals = {
                "basic": round(_safe(ex_row.get("酬  金", 0)), 0),
                "comm": round(_safe(ex_row.get("Basic Comm", 0)), 0),
                "allow": round(_safe(ex_row.get("Allowance", 0)), 0),
                "mpf": round(_safe(ex_row.get("MPF", 0)), 0),
                "net": round(_safe(ex_row["Total"]), 0),
            }
            sys_row = next(
                (row for row in sys_records if row["員工"] == name and row["地點"] == loc),
                None,
            )

            # Extra system detail
            att = att_map.get((name, loc), {})
            sales = sales_map.get((name, loc), {})
            emp = emp_map.get(name, {})
            ex_hrs = ex_hours_map.get((name, loc), {})

            monthly_hr = emp.get("monthly_hr")
            default_hr = _safe(emp.get("default_hr", 0))
            monthly_comm = emp.get("monthly_comm")
            default_comm = _safe(emp.get("default_comm", 0))

            result = {
                "month": payroll_month,
                "name": name,
                "location": loc,
                # Excel vs System financial columns
                "ex_basic": ex_vals["basic"],
                "sys_basic": 0,
                "ex_comm": ex_vals["comm"],
                "sys_comm": 0,
                "ex_allow": ex_vals["allow"],
                "sys_allow": 0,
                "ex_mpf": ex_vals["mpf"],
                "sys_mpf": 0,
                "ex_net": ex_vals["net"],
                "sys_net": 0,
                "diff": 0,
                "mismatch_fields": [],
                "mismatch_count": 0,
                "root_cause": [],
                "status": "❓ 系統找不到",
                # Excel & System detail: work hours
                "ex_days": int(ex_hrs.get("days") or 0),
                "ex_hours": round(ex_hrs.get("hours", 0), 2),
                "ex_ot": round(ex_hrs.get("ot", 0), 2),
                "sys_days": int(att.get("days_worked") or 0),
                "sys_hours": round(_safe(att.get("hours", 0)), 2),
                "sys_ot": round(_safe(att.get("ot_hours", 0)), 2),
                # System detail: adjustments
                "sys_expenses": round(_safe(att.get("expenses", 0)), 0),
                "sys_adjustment": round(_safe(att.get("adjustment", 0)), 0),
                "sys_bonus": round(_safe(att.get("attendance_bonus", 0)), 0),
                # System detail: sales
                "sys_sales_entries": int(sales.get("entries") or 0),
                "sys_sales_amount": round(_safe(sales.get("amount", 0)), 0),
                # System detail: rates
                "effective_hr": round(monthly_hr if monthly_hr is not None else default_hr, 2),
                "hr_overridden": monthly_hr is not None,
                "effective_comm_pct": round((monthly_comm if monthly_comm is not None else default_comm) * 100, 1),
                "comm_overridden": monthly_comm is not None,
            }

            if sys_row:
                result.update(
                    {
                        "sys_basic": round(sys_row["底薪"], 0),
                        "sys_comm": round(sys_row["總佣金"], 0),
                        "sys_allow": round(sys_row["津貼"], 0),
                        "sys_mpf": round(sys_row["MPF扣除"], 0),
                        "sys_net": round(sys_row["實發薪資"], 0),
                    }
                )
                mismatch_fields = []
                root_cause = []

                if result["ex_basic"] != result["sys_basic"]:
                    mismatch_fields.append("底薪")
                    if result["hr_overridden"]:
                        root_cause.append("月度時薪覆寫")
                    else:
                        root_cause.append("時薪/工時差異")

                if result["ex_comm"] != result["sys_comm"]:
                    mismatch_fields.append("佣金")
                    if result["comm_overridden"]:
                        root_cause.append("月度佣金覆寫")
                    elif result["sys_sales_amount"] == 0:
                        root_cause.append("系統無銷售紀錄")
                    else:
                        root_cause.append("佣金率/銷售差異")

                if result["ex_allow"] != result["sys_allow"]:
                    mismatch_fields.append("津貼")
                    root_cause.append("津貼差異")

                if result["ex_mpf"] != result["sys_mpf"]:
                    mismatch_fields.append("MPF")
                    root_cause.append("MPF差異")

                if result["ex_net"] != result["sys_net"]:
                    mismatch_fields.append("實發")

                result["mismatch_fields"] = mismatch_fields
                result["mismatch_count"] = len(mismatch_fields)
                result["root_cause"] = list(dict.fromkeys(root_cause))
                result["diff"] = result["sys_net"] - result["ex_net"]
                result["status"] = "✅ 匹配" if abs(result["diff"]) <= 1 else "❌ 不匹配"

            validation_results.append(result)

    # Default sort: largest absolute difference first
    validation_results.sort(key=lambda r: abs(r.get("diff", 0)), reverse=True)
    return validation_results
