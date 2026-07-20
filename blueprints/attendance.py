from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pandas as pd
from flask import Blueprint, flash, jsonify, redirect, request, session, url_for

from app_config import DEFAULT_BRAND_CODE
from repository import fetch_daily_attendance, get_db_connection, set_month_input_source, sync_attendance_summary
from services import log_audit, resolve_brand_for_current_user

bp = Blueprint("attendance", __name__)


def _resolve_brand_code():
    candidate = (request.form.get("brand") or request.args.get("brand") or "").strip().lower()
    if candidate:
        return resolve_brand_for_current_user(candidate)
    ref = request.referrer or ""
    if ref:
        qs = parse_qs(urlparse(ref).query)
        ref_brand = (qs.get("brand", [""])[0] or "").strip().lower()
        if ref_brand:
            return resolve_brand_for_current_user(ref_brand)
    return resolve_brand_for_current_user(DEFAULT_BRAND_CODE)


@bp.route("/delete_attendance/<int:id>", methods=["POST"])
def delete_attendance(id):
    brand_code = _resolve_brand_code()
    conn = get_db_connection()
    target = conn.execute(
        "SELECT brand_code, payroll_month, nick_name, location FROM Attendance WHERE id = ? AND brand_code = ?",
        (id, brand_code),
    ).fetchone()
    if target:
        month = target["payroll_month"]
        name = target["nick_name"]
        location = target["location"]
        conn.execute(
            "DELETE FROM DailyAttendance WHERE brand_code = ? AND payroll_month = ? AND nick_name = ? AND location = ?",
            (brand_code, month, name, location),
        )
        conn.execute("DELETE FROM Attendance WHERE id = ?", (id,))
        conn.commit()
        set_month_input_source(month, "web", brand_code=brand_code)
        flash(f"✅ 已徹底刪除 {name} 在 {location} 的考勤總表及所有每日明細", "success")
    else:
        flash("❌ 找不到該筆紀錄", "danger")
    conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/insert_attendance", methods=["POST"])
def insert_attendance():
    brand_code = _resolve_brand_code()
    payroll_month = request.form.get("payroll_month")
    nick_name = request.form.get("nick_name").strip()
    location = request.form.get("location").strip()
    days = int(request.form.get("days_worked", 0) or 0)
    hours = float(request.form.get("hours", 0) or 0)
    ot_hours = float(request.form.get("ot_hours", 0) or 0)
    expenses = float(request.form.get("expenses", 0) or 0)

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO Attendance (brand_code, payroll_month, nick_name, location, days_worked, hours, ot_hours, expenses)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(brand_code, payroll_month, nick_name, location) DO UPDATE SET
        days_worked = excluded.days_worked, hours = excluded.hours, ot_hours = excluded.ot_hours, expenses = excluded.expenses
        """,
        (brand_code, payroll_month, nick_name, location, days, hours, ot_hours, expenses),
    )
    conn.commit()
    conn.close()
    set_month_input_source(payroll_month, "web", brand_code=brand_code)
    flash("考勤紀錄新增成功", "success")
    return redirect(url_for("main.index", month=payroll_month, brand=brand_code))


@bp.route("/api/daily_attendance/<month>/<nick_name>/<path:location>")
def get_daily_attendance(month, nick_name, location):
    brand_code = _resolve_brand_code()
    return jsonify(fetch_daily_attendance(month, nick_name, location, brand_code=brand_code))


@bp.route("/update_daily_records", methods=["POST"])
def update_daily_records():
    brand_code = _resolve_brand_code()
    calc_month = request.form.get("calc_month")
    record_ids = request.form.getlist("record_id[]")
    roster_in_list = request.form.getlist("roster_in[]")
    roster_out_list = request.form.getlist("roster_out[]")
    in_times = request.form.getlist("in_time[]")
    out_times = request.form.getlist("out_time[]")
    normal_hours_list = request.form.getlist("normal_hours[]")

    conn = get_db_connection()
    old_rows = {}
    for record_id in record_ids:
        row = conn.execute("SELECT * FROM DailyAttendance WHERE id = ? AND brand_code = ?", (record_id, brand_code)).fetchone()
        old_rows[record_id] = dict(row) if row else None

    for index, record_id in enumerate(record_ids):
        in_time = in_times[index]
        out_time = out_times[index]
        r_in = roster_in_list[index] if index < len(roster_in_list) else None
        r_out = roster_out_list[index] if index < len(roster_out_list) else None
        normal_hours = float(normal_hours_list[index] or 8.0)
        try:
            delta = datetime.strptime(out_time, "%H:%M") - datetime.strptime(in_time, "%H:%M")
            actual_hours = delta.seconds / 3600
            raw_ot = actual_hours - normal_hours
        except Exception:
            actual_hours, raw_ot = 0, 0
        conn.execute(
            """
            UPDATE DailyAttendance
            SET roster_in = ?, roster_out = ?, in_time = ?, out_time = ?, normal_hours = ?, actual_hours = ?, ot_hours = ?
            WHERE id = ? AND brand_code = ?
            """,
            (r_in, r_out, in_time, out_time, normal_hours, actual_hours, raw_ot, record_id, brand_code),
        )

    conn.commit()
    set_month_input_source(calc_month, "web", brand_code=brand_code)
    sample = conn.execute(
        "SELECT nick_name, location FROM DailyAttendance WHERE id = ? AND brand_code = ?",
        (record_ids[0], brand_code),
    ).fetchone()
    if sample:
        sync_attendance_summary(calc_month, sample["nick_name"], sample["location"], brand_code=brand_code)
    try:
        for record_id in record_ids:
            new_row = conn.execute("SELECT * FROM DailyAttendance WHERE id = ? AND brand_code = ?", (record_id, brand_code)).fetchone()
            log_audit(
                "update",
                "DailyAttendance",
                record_id=record_id,
                old_value=old_rows.get(record_id),
                new_value=dict(new_row) if new_row else None,
                user=None,
                ip=request.remote_addr,
            )
    except Exception:
        pass
    conn.close()
    flash("✅ 考勤紀錄與常規工時已更新並重新結算！", "success")
    return redirect(url_for("main.index", month=calc_month, brand=brand_code))


@bp.route("/add_daily_attendance", methods=["POST"])
def add_daily_attendance():
    brand_code = _resolve_brand_code()
    month = request.form.get("payroll_month")
    name = request.form.get("nick_name")
    date = request.form.get("work_date")
    location = request.form.get("location")
    in_time = request.form.get("in_time")
    out_time = request.form.get("out_time")
    roster_in = request.form.get("roster_in")
    roster_out = request.form.get("roster_out")
    normal_hours = float(request.form.get("normal_hours", 8.0))

    try:
        delta = datetime.strptime(out_time, "%H:%M") - datetime.strptime(in_time, "%H:%M")
        actual_hours = delta.seconds / 3600
        raw_ot = actual_hours - normal_hours
    except Exception:
        actual_hours, raw_ot = 0, 0

    conn = get_db_connection()
    cursor = conn.execute(
        """
        INSERT INTO DailyAttendance (brand_code, payroll_month, work_date, nick_name, location, roster_in, roster_out, in_time, out_time, normal_hours, actual_hours, ot_hours)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (brand_code, month, date, name, location, roster_in or None, roster_out or None, in_time, out_time, normal_hours, actual_hours, raw_ot),
    )
    conn.commit()
    record_id = cursor.lastrowid
    try:
        log_audit(
            "create",
            "DailyAttendance",
            record_id=record_id,
            new_value={
                "payroll_month": month,
                "work_date": date,
                "nick_name": name,
                "location": location,
                "in_time": in_time,
                "out_time": out_time,
                "normal_hours": normal_hours,
                "actual_hours": actual_hours,
                "ot_hours": raw_ot,
            },
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    conn.close()
    set_month_input_source(month, "web", brand_code=brand_code)
    sync_attendance_summary(month, name, location, brand_code=brand_code)
    return jsonify({"status": "success", "message": "已新增考勤紀錄並同步總表"})


@bp.route("/update_daily_record_api", methods=["POST"])
def update_daily_record_api():
    if not session.get("user"):
        return {"status": "error", "message": "Unauthorized"}, 403

    record_id = request.form.get("id")
    roster_in = request.form.get("roster_in")
    roster_out = request.form.get("roster_out")
    in_time = request.form.get("in_time")
    out_time = request.form.get("out_time")
    normal_hours = float(request.form.get("normal_hours", 8.0))

    if not record_id or not in_time or not out_time:
        return jsonify({"status": "error", "message": "缺少必要的時間欄位"}), 400

    # 強制只取前 5 字元 (HH:MM)，濾除秒數
    in_hm = in_time[:5] if in_time else ""
    out_hm = out_time[:5] if out_time else ""

    try:
        t1 = datetime.strptime(in_hm, "%H:%M")
        t2 = datetime.strptime(out_hm, "%H:%M")
        diff = (t2 - t1).total_seconds() / 3600.0
        if diff < 0:
            diff += 24.0
        actual_hours = round(diff, 2)
        ot_hours = round(actual_hours - normal_hours, 2)
    except Exception:
        actual_hours = 0
        ot_hours = 0

    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE DailyAttendance
            SET roster_in = ?, roster_out = ?, in_time = ?, out_time = ?, normal_hours = ?, actual_hours = ?, ot_hours = ?
            WHERE id = ?
            """,
            (roster_in, roster_out, in_hm, out_hm, normal_hours, actual_hours, ot_hours, record_id)
        )
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@bp.route("/delete_daily_attendance/<int:id>", methods=["POST"])
def delete_daily_attendance(id):
    brand_code = _resolve_brand_code()
    conn = get_db_connection()
    record = conn.execute(
        "SELECT brand_code, payroll_month, nick_name, location FROM DailyAttendance WHERE id = ? AND brand_code = ?",
        (id, brand_code),
    ).fetchone()
    if record:
        month = record["payroll_month"]
        name = record["nick_name"]
        location = record["location"]
        old = conn.execute("SELECT * FROM DailyAttendance WHERE id = ? AND brand_code = ?", (id, brand_code)).fetchone()
        conn.execute("DELETE FROM DailyAttendance WHERE id = ? AND brand_code = ?", (id, brand_code))
        conn.commit()
        conn.close()
        set_month_input_source(month, "web", brand_code=brand_code)
        sync_attendance_summary(month, name, location, brand_code=brand_code)
        try:
            log_audit(
                "delete",
                "DailyAttendance",
                record_id=id,
                old_value=dict(old) if old else None,
                user=None,
                ip=request.remote_addr,
            )
        except Exception:
            pass
    else:
        conn.close()
    return jsonify({"status": "success", "message": "紀錄已刪除並重新計算總表"})


@bp.route("/update_attendance", methods=["POST"])
def update_attendance():
    brand_code = _resolve_brand_code()
    month = request.form.get("calc_month")
    name = request.form.get("nick_name")
    location = request.form.get("location")
    expenses = float(request.form.get("expenses", 0) or 0)
    adjustment = float(request.form.get("adjustment", 0) or 0)
    bonus = float(request.form.get("attendance_bonus", 0) or 0)
    monthly_rate_str = request.form.get("monthly_hourly_rate", "").strip()
    monthly_salary_str = request.form.get("monthly_salary_override", "").strip()

    conn = get_db_connection()
    old = conn.execute(
        "SELECT * FROM Attendance WHERE brand_code = ? AND payroll_month = ? AND nick_name = ? AND location = ?",
        (brand_code, month, name, location),
    ).fetchone()
    conn.execute(
        """
        INSERT OR IGNORE INTO Attendance (brand_code, payroll_month, nick_name, location, days_worked, hours, ot_hours)
        VALUES (?, ?, ?, ?, 0, 0, 0)
        """,
        (brand_code, month, name, location),
    )
    conn.execute(
        """
        UPDATE Attendance
        SET expenses = ?, adjustment = ?, attendance_bonus = ?
        WHERE brand_code = ? AND payroll_month = ? AND nick_name = ? AND location = ?
        """,
        (expenses, adjustment, bonus, brand_code, month, name, location),
    )

    hr_val = float(monthly_rate_str) if monthly_rate_str != "" else None
    salary_val = float(monthly_salary_str) if monthly_salary_str != "" else None

    conn.execute(
        """
        INSERT INTO MonthlyRates (brand_code, payroll_month, nick_name, hourly_rate, monthly_salary)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(brand_code, payroll_month, nick_name) DO UPDATE SET
            hourly_rate = excluded.hourly_rate,
            monthly_salary = excluded.monthly_salary
        """,
        (brand_code, month, name, hr_val, salary_val)
    )
    conn.commit()
    set_month_input_source(month, "web", brand_code=brand_code)
    new = conn.execute(
        "SELECT * FROM Attendance WHERE brand_code = ? AND payroll_month = ? AND nick_name = ? AND location = ?",
        (brand_code, month, name, location),
    ).fetchone()
    try:
        log_audit(
            "update",
            "Attendance_and_Rates",
            record_id=new["id"] if new else None,
            old_value=dict(old) if old else None,
            new_value=dict(new) if new else None,
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    conn.close()
    flash(f"✅ 已儲存 {name} 在 {location} 的月結微調與時薪設定", "success")
    return redirect(url_for("main.index", month=month, brand=brand_code))
