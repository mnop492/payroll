from datetime import datetime

import pandas as pd
from flask import Blueprint, flash, jsonify, redirect, request, url_for

from repository import fetch_daily_attendance, get_db_connection, set_month_input_source, sync_attendance_summary
from services import log_audit

bp = Blueprint("attendance", __name__)


@bp.route("/delete_attendance/<int:id>", methods=["POST"])
def delete_attendance(id):
    conn = get_db_connection()
    target = conn.execute(
        "SELECT payroll_month, nick_name, location FROM Attendance WHERE id = ?",
        (id,),
    ).fetchone()
    if target:
        month = target["payroll_month"]
        name = target["nick_name"]
        location = target["location"]
        conn.execute(
            "DELETE FROM DailyAttendance WHERE payroll_month = ? AND nick_name = ? AND location = ?",
            (month, name, location),
        )
        conn.execute("DELETE FROM Attendance WHERE id = ?", (id,))
        conn.commit()
        set_month_input_source(month, "web")
        flash(f"✅ 已徹底刪除 {name} 在 {location} 的考勤總表及所有每日明細", "success")
    else:
        flash("❌ 找不到該筆紀錄", "danger")
    conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/insert_attendance", methods=["POST"])
def insert_attendance():
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
        INSERT INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours, expenses)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(payroll_month, nick_name, location) DO UPDATE SET
        days_worked = excluded.days_worked, hours = excluded.hours, ot_hours = excluded.ot_hours, expenses = excluded.expenses
        """,
        (payroll_month, nick_name, location, days, hours, ot_hours, expenses),
    )
    conn.commit()
    conn.close()
    set_month_input_source(payroll_month, "web")
    flash("考勤紀錄新增成功", "success")
    return redirect(url_for("main.index"))


@bp.route("/api/daily_attendance/<month>/<nick_name>/<path:location>")
def get_daily_attendance(month, nick_name, location):
    return jsonify(fetch_daily_attendance(month, nick_name, location))


@bp.route("/update_daily_records", methods=["POST"])
def update_daily_records():
    calc_month = request.form.get("calc_month")
    record_ids = request.form.getlist("record_id[]")
    in_times = request.form.getlist("in_time[]")
    out_times = request.form.getlist("out_time[]")
    normal_hours_list = request.form.getlist("normal_hours[]")

    conn = get_db_connection()
    old_rows = {}
    for record_id in record_ids:
        row = conn.execute("SELECT * FROM DailyAttendance WHERE id = ?", (record_id,)).fetchone()
        old_rows[record_id] = dict(row) if row else None

    for index, record_id in enumerate(record_ids):
        in_time = in_times[index]
        out_time = out_times[index]
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
            SET in_time = ?, out_time = ?, normal_hours = ?, actual_hours = ?, ot_hours = ?
            WHERE id = ?
            """,
            (in_time, out_time, normal_hours, actual_hours, raw_ot, record_id),
        )

    conn.commit()
    set_month_input_source(calc_month, "web")
    sample = conn.execute("SELECT nick_name, location FROM DailyAttendance WHERE id = ?", (record_ids[0],)).fetchone()
    if sample:
        sync_attendance_summary(calc_month, sample["nick_name"], sample["location"])
    try:
        for record_id in record_ids:
            new_row = conn.execute("SELECT * FROM DailyAttendance WHERE id = ?", (record_id,)).fetchone()
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
    return redirect(url_for("main.index", month=calc_month))


@bp.route("/add_daily_attendance", methods=["POST"])
def add_daily_attendance():
    month = request.form.get("payroll_month")
    name = request.form.get("nick_name")
    date = request.form.get("work_date")
    location = request.form.get("location")
    in_time = request.form.get("in_time")
    out_time = request.form.get("out_time")
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
        INSERT INTO DailyAttendance (payroll_month, work_date, nick_name, location, in_time, out_time, normal_hours, actual_hours, ot_hours)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (month, date, name, location, in_time, out_time, normal_hours, actual_hours, raw_ot),
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
    set_month_input_source(month, "web")
    sync_attendance_summary(month, name, location)
    return jsonify({"status": "success", "message": "已新增考勤紀錄並同步總表"})


@bp.route("/delete_daily_attendance/<int:id>", methods=["POST"])
def delete_daily_attendance(id):
    conn = get_db_connection()
    record = conn.execute(
        "SELECT payroll_month, nick_name, location FROM DailyAttendance WHERE id = ?",
        (id,),
    ).fetchone()
    if record:
        month = record["payroll_month"]
        name = record["nick_name"]
        location = record["location"]
        old = conn.execute("SELECT * FROM DailyAttendance WHERE id = ?", (id,)).fetchone()
        conn.execute("DELETE FROM DailyAttendance WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        set_month_input_source(month, "web")
        sync_attendance_summary(month, name, location)
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
    month = request.form.get("calc_month")
    name = request.form.get("nick_name")
    location = request.form.get("location")
    expenses = float(request.form.get("expenses", 0) or 0)
    adjustment = float(request.form.get("adjustment", 0) or 0)
    bonus = float(request.form.get("attendance_bonus", 0) or 0)
    monthly_rate_str = request.form.get("monthly_hourly_rate", "").strip()

    conn = get_db_connection()
    old = conn.execute(
        "SELECT * FROM Attendance WHERE payroll_month = ? AND nick_name = ? AND location = ?",
        (month, name, location),
    ).fetchone()
    conn.execute(
        """
        INSERT OR IGNORE INTO Attendance (payroll_month, nick_name, location, days_worked, hours, ot_hours)
        VALUES (?, ?, ?, 0, 0, 0)
        """,
        (month, name, location),
    )
    conn.execute(
        """
        UPDATE Attendance
        SET expenses = ?, adjustment = ?, attendance_bonus = ?
        WHERE payroll_month = ? AND nick_name = ? AND location = ?
        """,
        (expenses, adjustment, bonus, month, name, location),
    )
    if monthly_rate_str == "":
        conn.execute(
            "DELETE FROM MonthlyRates WHERE payroll_month = ? AND nick_name = ?",
            (month, name),
        )
    else:
        monthly_rate = float(monthly_rate_str)
        existing = conn.execute(
            "SELECT id FROM MonthlyRates WHERE payroll_month = ? AND nick_name = ?",
            (month, name),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE MonthlyRates SET hourly_rate = ? WHERE payroll_month = ? AND nick_name = ?",
                (monthly_rate, month, name),
            )
        else:
            conn.execute(
                "INSERT INTO MonthlyRates (payroll_month, nick_name, hourly_rate) VALUES (?, ?, ?)",
                (month, name, monthly_rate),
            )
    conn.commit()
    set_month_input_source(month, "web")
    new = conn.execute(
        "SELECT * FROM Attendance WHERE payroll_month = ? AND nick_name = ? AND location = ?",
        (month, name, location),
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
    return redirect(url_for("main.index", month=month))
