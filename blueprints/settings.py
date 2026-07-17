import csv
import io
import json
import logging
import os
import shutil
import sqlite3
import re
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from werkzeug.security import generate_password_hash

import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app_config import BACKUP_FOLDER, DB_PATH, DEFAULT_ADMIN_USERNAME, DEFAULT_BRAND_CODE
from repository import (
    fetch_manage_locations_context,
    fetch_manage_products_context,
    fetch_settings_context,
    get_all_brands,
    get_auto_backup_settings,
    get_available_brands,
    get_brand_name,
    get_db_connection,
    get_user_brand_permissions_map,
    grant_all_active_brands_to_user,
    set_auto_backup_settings,
    set_user_brand_permissions,
    try_claim_auto_backup_run,
)
from services import admin_required, get_current_user_available_brands, is_audit_admin, log_audit, resolve_brand_for_current_user

bp = Blueprint("settings", __name__)

_auto_backup_worker_started = False
_auto_backup_lock = threading.Lock()


def _is_valid_backup_time(value):
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(value or "").strip()))


def _create_backup_file(prefix="payroll_backup"):
    os.makedirs(BACKUP_FOLDER, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.db"
    target = os.path.join(BACKUP_FOLDER, filename)
    shutil.copy2(DB_PATH, target)
    return filename


def _run_scheduled_backup_if_due():
    settings = get_auto_backup_settings()
    if not settings.get("enabled"):
        return

    backup_time = (settings.get("backup_time") or "02:00").strip()
    if not _is_valid_backup_time(backup_time):
        return

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_hhmm = now.strftime("%H:%M")
    if current_hhmm < backup_time:
        return

    if not try_claim_auto_backup_run(today, current_hhmm):
        return

    filename = _create_backup_file(prefix="payroll_auto_backup")
    logging.info("Nightly auto backup created: %s", filename)


def start_auto_backup_worker():
    global _auto_backup_worker_started
    with _auto_backup_lock:
        if _auto_backup_worker_started:
            return

        def _loop():
            while True:
                try:
                    _run_scheduled_backup_if_due()
                except Exception as exc:
                    logging.exception("Auto backup worker error: %s", exc)
                time.sleep(45)

        t = threading.Thread(target=_loop, name="payroll-auto-backup", daemon=True)
        t.start()
        _auto_backup_worker_started = True


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


@bp.route("/settings")
def settings():
    current_month = request.args.get("month", pd.Timestamp.now().strftime("%Y-%m"))
    brand_code = _resolve_brand_code()
    employees, monthly_map, monthly_comm_map = fetch_settings_context(current_month, brand_code=brand_code)
    return render_template(
        "settings.html",
        employees=employees,
        current_month=current_month,
        current_brand=brand_code,
        current_brand_name=get_brand_name(brand_code),
        available_brands=get_current_user_available_brands(),
        monthly_map=monthly_map,
        monthly_comm_map=monthly_comm_map,
    )


@bp.route("/manage_users")
@admin_required
def manage_users():
    conn = get_db_connection()
    users = conn.execute(
        "SELECT id, username, is_admin, is_active, created_at, updated_at FROM Users ORDER BY username"
    ).fetchall()
    conn.close()
    return render_template(
        "manage_users.html",
        users=users,
        available_brands=get_available_brands(),
        user_brand_map=get_user_brand_permissions_map(),
    )


@bp.route("/manage_backups")
@admin_required
def manage_backups():
    os.makedirs(BACKUP_FOLDER, exist_ok=True)
    files = []
    for name in sorted(os.listdir(BACKUP_FOLDER), reverse=True):
        if not name.endswith(".db"):
            continue
        path = os.path.join(BACKUP_FOLDER, name)
        stat = os.stat(path)
        size_mb = round(stat.st_size / (1024 * 1024), 2)
        files.append(
            {
                "name": name,
                "size_mb": size_mb,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return render_template("manage_backups.html", files=files, auto_backup=get_auto_backup_settings())


@bp.route("/create_backup", methods=["POST"])
@admin_required
def create_backup():
    filename = _create_backup_file(prefix="payroll_backup")
    try:
        log_audit(
            "backup",
            "Database",
            record_id=filename,
            new_value={"filename": filename},
            user=session.get("user"),
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash(f"✅ 已建立備份：{filename}", "success")
    return redirect(url_for("settings.manage_backups"))


@bp.route("/update_auto_backup", methods=["POST"])
@admin_required
def update_auto_backup():
    enabled = request.form.get("enabled") == "on"
    backup_time = (request.form.get("backup_time") or "02:00").strip()

    if not _is_valid_backup_time(backup_time):
        flash("⚠️ 自動備份時間格式錯誤，請使用 HH:MM（24 小時制）。", "danger")
        return redirect(url_for("settings.manage_backups"))

    set_auto_backup_settings(enabled=enabled, backup_time=backup_time)
    state = "已啟用" if enabled else "已停用"
    flash(f"✅ 每晚自動備份設定已更新：{state}，時間 {backup_time}", "success")
    return redirect(url_for("settings.manage_backups"))


@bp.route("/restore_backup", methods=["POST"])
@admin_required
def restore_backup():
    filename = (request.form.get("filename") or "").strip()
    safe_name = os.path.basename(filename)
    source = os.path.join(BACKUP_FOLDER, safe_name)
    if not safe_name or not os.path.exists(source):
        flash("⚠️ 找不到指定備份檔", "danger")
        return redirect(url_for("settings.manage_backups"))

    pre_restore_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_file = f"pre_restore_{pre_restore_ts}.db"
    safety_path = os.path.join(BACKUP_FOLDER, safety_file)
    shutil.copy2(DB_PATH, safety_path)

    shutil.copy2(source, DB_PATH)
    try:
        log_audit(
            "restore",
            "Database",
            record_id=safe_name,
            new_value={"restored_from": safe_name, "pre_restore_backup": safety_file},
            user=session.get("user"),
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash(f"✅ 已還原備份：{safe_name}（系統已保留還原前快照 {safety_file}）", "success")
    return redirect(url_for("settings.manage_backups"))


@bp.route("/add_user", methods=["POST"])
@admin_required
def add_user():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    is_admin = 1 if request.form.get("is_admin") == "on" else 0

    if not username or not password:
        flash("請輸入使用者名稱與密碼。", "warning")
        return redirect(url_for("settings.manage_users"))

    conn = get_db_connection()
    try:
        cur = conn.execute(
            "INSERT INTO Users (username, password_hash, is_admin, is_active) VALUES (?, ?, ?, 1)",
            (username, generate_password_hash(password), is_admin),
        )
        conn.commit()
        grant_all_active_brands_to_user(username)
        try:
            log_audit(
                "create",
                "Users",
                record_id=cur.lastrowid,
                new_value={"username": username, "is_admin": bool(is_admin), "is_active": True},
                user=session.get("user"),
                ip=request.remote_addr,
            )
        except Exception:
            pass
        flash(f"✅ 已新增使用者：{username}", "success")
    except sqlite3.IntegrityError:
        flash("⚠️ 使用者名稱已存在", "danger")
    finally:
        conn.close()
    return redirect(url_for("settings.manage_users"))


@bp.route("/update_user_role", methods=["POST"])
@admin_required
def update_user_role():
    user_id = request.form.get("id")
    is_admin = 1 if request.form.get("is_admin") == "on" else 0

    if not user_id:
        flash("⚠️ 缺少使用者 ID", "danger")
        return redirect(url_for("settings.manage_users"))

    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    if not old:
        conn.close()
        flash("⚠️ 找不到該使用者", "danger")
        return redirect(url_for("settings.manage_users"))

    if old["username"] == session.get("user") and not is_admin:
        conn.close()
        flash("⚠️ 不能取消自己 admin 權限", "warning")
        return redirect(url_for("settings.manage_users"))

    conn.execute(
        "UPDATE Users SET is_admin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (is_admin, user_id),
    )
    conn.commit()
    new = conn.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    try:
        log_audit(
            "update",
            "Users",
            record_id=user_id,
            old_value=dict(old),
            new_value=dict(new) if new else None,
            user=session.get("user"),
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash("✅ 使用者權限已更新", "success")
    return redirect(url_for("settings.manage_users"))


@bp.route("/update_user_status", methods=["POST"])
@admin_required
def update_user_status():
    user_id = request.form.get("id")
    is_active = 1 if request.form.get("is_active") == "on" else 0

    if not user_id:
        flash("⚠️ 缺少使用者 ID", "danger")
        return redirect(url_for("settings.manage_users"))

    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    if not old:
        conn.close()
        flash("⚠️ 找不到該使用者", "danger")
        return redirect(url_for("settings.manage_users"))

    if old["username"] == session.get("user") and not is_active:
        conn.close()
        flash("⚠️ 不能停用自己", "warning")
        return redirect(url_for("settings.manage_users"))

    if old["username"] == DEFAULT_ADMIN_USERNAME and not is_active:
        conn.close()
        flash("⚠️ 不能停用預設管理員", "warning")
        return redirect(url_for("settings.manage_users"))

    conn.execute(
        "UPDATE Users SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (is_active, user_id),
    )
    conn.commit()
    new = conn.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    try:
        log_audit(
            "update",
            "Users",
            record_id=user_id,
            old_value=dict(old),
            new_value=dict(new) if new else None,
            user=session.get("user"),
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash("✅ 使用者狀態已更新", "success")
    return redirect(url_for("settings.manage_users"))


@bp.route("/update_user_password", methods=["POST"])
@admin_required
def update_user_password():
    user_id = request.form.get("id")
    password = request.form.get("new_password") or ""

    if not user_id or not password:
        flash("⚠️ 請輸入新密碼", "warning")
        return redirect(url_for("settings.manage_users"))

    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    if not old:
        conn.close()
        flash("⚠️ 找不到該使用者", "danger")
        return redirect(url_for("settings.manage_users"))

    conn.execute(
        "UPDATE Users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (generate_password_hash(password), user_id),
    )
    conn.commit()
    new = conn.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    try:
        log_audit(
            "update_password",
            "Users",
            record_id=user_id,
            old_value={"username": old["username"]},
            new_value={"username": new["username"] if new else old["username"]},
            user=session.get("user"),
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash("✅ 密碼已更新", "success")
    return redirect(url_for("settings.manage_users"))


@bp.route("/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    if not old:
        conn.close()
        flash("⚠️ 找不到該使用者", "danger")
        return redirect(url_for("settings.manage_users"))

    if old["username"] == session.get("user"):
        conn.close()
        flash("⚠️ 不能刪除自己", "warning")
        return redirect(url_for("settings.manage_users"))

    if old["username"] == DEFAULT_ADMIN_USERNAME:
        conn.close()
        flash("⚠️ 不能刪除預設管理員", "warning")
        return redirect(url_for("settings.manage_users"))

    conn.execute("DELETE FROM UserBrandPermissions WHERE username = ?", (old["username"],))
    conn.execute("DELETE FROM Users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    try:
        log_audit(
            "delete",
            "Users",
            record_id=user_id,
            old_value=dict(old),
            user=session.get("user"),
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash(f"✅ 已刪除使用者：{old['username']}", "success")
    return redirect(url_for("settings.manage_users"))


@bp.route("/update_user_brands", methods=["POST"])
@admin_required
def update_user_brands():
    user_id = request.form.get("id")
    brand_codes = request.form.getlist("brand_codes")

    if not user_id:
        flash("⚠️ 缺少使用者 ID", "danger")
        return redirect(url_for("settings.manage_users"))

    conn = get_db_connection()
    user_row = conn.execute("SELECT username FROM Users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not user_row:
        flash("⚠️ 找不到該使用者", "danger")
        return redirect(url_for("settings.manage_users"))

    username = user_row["username"]
    if not brand_codes:
        flash("⚠️ 至少要保留一個可操作品牌。", "warning")
        return redirect(url_for("settings.manage_users"))
    set_user_brand_permissions(username, brand_codes)
    try:
        log_audit(
            "update",
            "UserBrandPermissions",
            record_id=user_id,
            new_value={"username": username, "brand_codes": brand_codes},
            user=session.get("user"),
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash(f"✅ 已更新 {username} 的品牌授權", "success")
    return redirect(url_for("settings.manage_users"))


@bp.route("/update_monthly_rate", methods=["POST"])
def update_monthly_rate():
    brand_code = _resolve_brand_code()
    payroll_month = request.form.get("payroll_month") or pd.Timestamp.now().strftime("%Y-%m")
    nick_name = request.form.get("nick_name")
    monthly_rate_value = request.form.get("monthly_hourly_rate", "").strip()

    conn = get_db_connection()
    old = conn.execute(
        "SELECT * FROM MonthlyRates WHERE brand_code = ? AND payroll_month = ? AND nick_name = ?",
        (brand_code, payroll_month, nick_name),
    ).fetchone()
    old_dict = dict(old) if old else None

    if monthly_rate_value == "":
        if old:
            conn.execute(
                "DELETE FROM MonthlyRates WHERE brand_code = ? AND payroll_month = ? AND nick_name = ?",
                (brand_code, payroll_month, nick_name),
            )
            conn.commit()
            try:
                log_audit("delete", "MonthlyRates", record_id=f"{payroll_month}:{nick_name}", old_value=old_dict, user=None, ip=request.remote_addr)
            except Exception:
                pass
            flash(f"✅ 已移除 {nick_name} 的 {payroll_month} 月度時薪覆寫，改回預設時薪。", "success")
        else:
            flash(f"⚠️ {nick_name} 在 {payroll_month} 沒有設定可移除。", "warning")
    else:
        hourly_rate = float(monthly_rate_value)
        if old:
            conn.execute(
                "UPDATE MonthlyRates SET hourly_rate = ? WHERE brand_code = ? AND payroll_month = ? AND nick_name = ?",
                (hourly_rate, brand_code, payroll_month, nick_name),
            )
            action = "update"
        else:
            conn.execute(
                "INSERT INTO MonthlyRates (brand_code, payroll_month, nick_name, hourly_rate) VALUES (?, ?, ?, ?)",
                (brand_code, payroll_month, nick_name, hourly_rate),
            )
            action = "create"
        conn.commit()
        new = conn.execute(
            "SELECT * FROM MonthlyRates WHERE brand_code = ? AND payroll_month = ? AND nick_name = ?",
            (brand_code, payroll_month, nick_name),
        ).fetchone()
        try:
            log_audit(action, "MonthlyRates", record_id=f"{payroll_month}:{nick_name}", old_value=old_dict, new_value=dict(new) if new else None, user=None, ip=request.remote_addr)
        except Exception:
            pass
        flash(f"✅ 已儲存 {nick_name} 的 {payroll_month} 月度時薪：${hourly_rate:.2f}", "success")

    conn.close()
    return redirect(url_for("settings.settings", month=payroll_month, brand=brand_code))


@bp.route("/update_employee", methods=["POST"])
def update_employee():
    brand_code = _resolve_brand_code()
    emp_id = request.form.get("id")
    full_name = request.form.get("full_name")
    hourly_rate = float(request.form.get("hourly_rate", 0))
    allowance = float(request.form.get("allowance", 0))
    commission_rate = float(request.form.get("commission_rate", 0.03))
    mpf_start_month = request.form.get("mpf_start_month")
    
    # 🌟 新增抓取計薪模式與月薪
    salary_type = request.form.get("salary_type", "hourly")
    monthly_salary = float(request.form.get("monthly_salary", 0))
    monthly_hourly_rate = (request.form.get("monthly_hourly_rate", "") or "").strip()
    monthly_commission_rate = (request.form.get("monthly_commission_rate", "") or "").strip()

    payroll_month = request.form.get("payroll_month") or pd.Timestamp.now().strftime("%Y-%m")
    # ... (保留原有的 monthly_hourly_rate 等變數) ...

    if emp_id:
        conn = get_db_connection()
        try:
            old = conn.execute("SELECT * FROM Employees WHERE id = ? AND brand_code = ?", (emp_id, brand_code)).fetchone()
            if not old:
                flash("⚠️ 找不到該品牌下的員工資料", "danger")
                return redirect(url_for("settings.settings", month=payroll_month, brand=brand_code))
            old_dict = dict(old) if old else None
            nick_name = old["nick_name"] if old else None
            # 🌟 更新 SQL，寫入 salary_type 與 monthly_salary
            conn.execute(
                """
                UPDATE Employees
                SET full_name = ?, hourly_rate = ?, allowance = ?, commission_rate = ?, mpf_start_month = ?, salary_type = ?, monthly_salary = ?
                WHERE id = ? AND brand_code = ?
                """,
                (full_name, hourly_rate, allowance, commission_rate, mpf_start_month, salary_type, monthly_salary, emp_id, brand_code),
            )
            conn.commit()
            if nick_name:
                if monthly_hourly_rate == "" and monthly_commission_rate == "":
                    conn.execute(
                        "DELETE FROM MonthlyRates WHERE brand_code = ? AND payroll_month = ? AND nick_name = ?",
                        (brand_code, payroll_month, nick_name),
                    )
                else:
                    hr_val = float(monthly_hourly_rate) if monthly_hourly_rate != "" else None
                    comm_val = float(monthly_commission_rate) if monthly_commission_rate != "" else None
                    conn.execute(
                        """
                        INSERT INTO MonthlyRates (brand_code, payroll_month, nick_name, hourly_rate, commission_rate)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(brand_code, payroll_month, nick_name) DO UPDATE SET
                        hourly_rate = excluded.hourly_rate,
                        commission_rate = excluded.commission_rate
                        """,
                        (brand_code, payroll_month, nick_name, hr_val, comm_val),
                    )
                conn.commit()
            new = conn.execute("SELECT * FROM Employees WHERE id = ? AND brand_code = ?", (emp_id, brand_code)).fetchone()
            try:
                log_audit("update", "Employees", record_id=emp_id, old_value=old_dict, new_value=dict(new) if new else None, user=None, ip=request.remote_addr)
            except Exception:
                pass
            flash("✅ 員工主檔資料已成功更新", "success")
        except Exception as exc:
            flash(f"⚠️ 更新失敗：{str(exc)}", "danger")
        finally:
            conn.close()
    return redirect(url_for("settings.settings", month=payroll_month, brand=brand_code))


@bp.route("/add_employee", methods=["POST"])
def add_employee():
    brand_code = _resolve_brand_code()
    payroll_month = request.form.get("payroll_month") or pd.Timestamp.now().strftime("%Y-%m")

    nick_name = (request.form.get("nick_name") or "").strip()
    full_name = (request.form.get("full_name") or "").strip()
    salary_type = (request.form.get("salary_type") or "hourly").strip().lower()
    if salary_type not in ("hourly", "monthly"):
        salary_type = "hourly"
    mpf_start_month = (request.form.get("mpf_start_month") or "").strip() or None
    monthly_hourly_rate = (request.form.get("monthly_hourly_rate", "") or "").strip()
    monthly_commission_rate = (request.form.get("monthly_commission_rate", "") or "").strip()

    if not nick_name:
        flash("⚠️ 請輸入員工暱稱", "warning")
        return redirect(url_for("settings.settings", month=payroll_month, brand=brand_code))

    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    hourly_rate = _to_float(request.form.get("hourly_rate", 0), 0)
    allowance = _to_float(request.form.get("allowance", 0), 0)
    commission_rate = _to_float(request.form.get("commission_rate", 0.03), 0.03)
    monthly_salary = _to_float(request.form.get("monthly_salary", 0), 0)

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO Employees (brand_code, nick_name, full_name, hourly_rate, allowance, commission_rate, mpf_start_month, salary_type, monthly_salary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (brand_code, nick_name, full_name, hourly_rate, allowance, commission_rate, mpf_start_month, salary_type, monthly_salary),
        )

        if monthly_hourly_rate != "" or monthly_commission_rate != "":
            hr_val = _to_float(monthly_hourly_rate, 0) if monthly_hourly_rate != "" else None
            comm_val = _to_float(monthly_commission_rate, 0) if monthly_commission_rate != "" else None
            conn.execute(
                """
                INSERT INTO MonthlyRates (brand_code, payroll_month, nick_name, hourly_rate, commission_rate)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(brand_code, payroll_month, nick_name) DO UPDATE SET
                hourly_rate = excluded.hourly_rate,
                commission_rate = excluded.commission_rate
                """,
                (brand_code, payroll_month, nick_name, hr_val, comm_val),
            )

        conn.commit()
        try:
            new = conn.execute("SELECT * FROM Employees WHERE id = ? AND brand_code = ?", (cursor.lastrowid, brand_code)).fetchone()
            log_audit("create", "Employees", record_id=cursor.lastrowid, new_value=dict(new) if new else None, user=None, ip=request.remote_addr)
        except Exception:
            pass
        flash(f"✅ 已新增員工：{nick_name}", "success")
    except sqlite3.IntegrityError:
        flash(f"⚠️ 員工暱稱重複：{nick_name}（同品牌不可重複）", "warning")
    except Exception as exc:
        flash(f"⚠️ 新增員工失敗：{str(exc)}", "danger")
    finally:
        conn.close()

    return redirect(url_for("settings.settings", month=payroll_month, brand=brand_code))


@bp.route("/delete_employee/<int:emp_id>", methods=["POST"])
def delete_employee(emp_id):
    brand_code = _resolve_brand_code()
    payroll_month = request.form.get("payroll_month") or pd.Timestamp.now().strftime("%Y-%m")

    conn = get_db_connection()
    try:
        old = conn.execute("SELECT * FROM Employees WHERE id = ? AND brand_code = ?", (emp_id, brand_code)).fetchone()
        if not old:
            flash("⚠️ 找不到該品牌下的員工資料", "warning")
            return redirect(url_for("settings.settings", month=payroll_month, brand=brand_code))

        nick_name = old["nick_name"]
        has_attendance = conn.execute(
            "SELECT 1 FROM Attendance WHERE brand_code = ? AND nick_name = ? LIMIT 1",
            (brand_code, nick_name),
        ).fetchone()
        has_sales = conn.execute(
            "SELECT 1 FROM Sales WHERE brand_code = ? AND promoter_name = ? LIMIT 1",
            (brand_code, nick_name),
        ).fetchone()

        if has_attendance or has_sales:
            flash(f"⚠️ 無法刪除 {nick_name}：已有出勤或銷售資料", "warning")
            return redirect(url_for("settings.settings", month=payroll_month, brand=brand_code))

        conn.execute("DELETE FROM MonthlyRates WHERE brand_code = ? AND nick_name = ?", (brand_code, nick_name))
        conn.execute("DELETE FROM Employees WHERE id = ? AND brand_code = ?", (emp_id, brand_code))
        conn.commit()

        try:
            log_audit("delete", "Employees", record_id=emp_id, old_value=dict(old), user=None, ip=request.remote_addr)
        except Exception:
            pass
        flash(f"✅ 已刪除員工：{nick_name}", "success")
    except Exception as exc:
        flash(f"⚠️ 刪除員工失敗：{str(exc)}", "danger")
    finally:
        conn.close()

    return redirect(url_for("settings.settings", month=payroll_month, brand=brand_code))


@bp.route("/save_special_comm", methods=["POST"])
def save_special_comm():
    brand_code = _resolve_brand_code()
    model = request.form.get("model").strip()
    start = request.form.get("start")
    end = request.form.get("end")
    rate = request.form.get("rate")
    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO SpecialCommissions (brand_code, model, start_month, end_month, rate) VALUES (?, ?, ?, ?, ?)",
        (brand_code, model, start, end, float(rate)),
    )
    conn.commit()
    try:
        log_audit("create", "SpecialCommissions", record_id=cursor.lastrowid, new_value={"model": model, "start_month": start, "end_month": end, "rate": float(rate)}, user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()
    flash(f"已成功加入 {model} 的特殊佣金規則", "success")
    return redirect(url_for("settings.settings", brand=brand_code))


@bp.route("/delete_special_comm/<int:id>")
def delete_special_comm(id):
    brand_code = _resolve_brand_code()
    conn = get_db_connection()
    old = conn.execute("SELECT * FROM SpecialCommissions WHERE id = ? AND brand_code = ?", (id, brand_code)).fetchone()
    conn.execute("DELETE FROM SpecialCommissions WHERE id = ? AND brand_code = ?", (id, brand_code))
    conn.commit()
    conn.close()
    try:
        log_audit("delete", "SpecialCommissions", record_id=id, old_value=dict(old) if old else None, user=None, ip=request.remote_addr)
    except Exception:
        pass
    return redirect(request.referrer or url_for("settings.manage_products", brand=brand_code))


@bp.route("/update_emp_mpf", methods=["POST"])
def update_emp_mpf():
    brand_code = _resolve_brand_code()
    name = request.form.get("name")
    start_month = request.form.get("start_month")
    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Employees WHERE brand_code = ? AND nick_name = ?", (brand_code, name)).fetchone()
    conn.execute("UPDATE Employees SET mpf_start_month = ? WHERE brand_code = ? AND nick_name = ?", (start_month, brand_code, name))
    conn.commit()
    new = conn.execute("SELECT * FROM Employees WHERE brand_code = ? AND nick_name = ?", (brand_code, name)).fetchone()
    try:
        log_audit("update", "Employees", record_id=new["id"] if new else None, old_value=dict(old) if old else None, new_value=dict(new) if new else None, user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()
    flash(f"已更新 {name} 的 MPF 起扣月份", "success")
    return redirect(url_for("settings.settings", brand=brand_code))


@bp.route("/manage_products")
def manage_products():
    brand_code = _resolve_brand_code()
    products, special_rules = fetch_manage_products_context(brand_code=brand_code)
    return render_template(
        "manage_products.html",
        products=products,
        special_rules=special_rules,
        current_brand=brand_code,
        current_brand_name=get_brand_name(brand_code),
        available_brands=get_current_user_available_brands(),
    )


@bp.route("/update_product_config", methods=["POST"])
def update_product_config():
    brand_code = _resolve_brand_code()
    model = request.form.get("model")
    update_type = request.form.get("update_type")
    rate = float(request.form.get("rate"))
    conn = get_db_connection()
    if update_type == "permanent":
        old = conn.execute("SELECT * FROM Products WHERE brand_code = ? AND model = ?", (brand_code, model)).fetchone()
        conn.execute("UPDATE Products SET commission_rate = ? WHERE brand_code = ? AND model = ?", (rate, brand_code, model))
        conn.commit()
        new = conn.execute("SELECT * FROM Products WHERE brand_code = ? AND model = ?", (brand_code, model)).fetchone()
        try:
            log_audit("update", "Products", record_id=new["id"] if new else None, old_value=dict(old) if old else None, new_value=dict(new) if new else None, user=None, ip=request.remote_addr)
        except Exception:
            pass
        flash(f"✅ 已更新 {model} 的永久佣金比例為 {rate * 100}%", "success")
    else:
        start = request.form.get("start_month")
        end = request.form.get("end_month")
        if not start or not end:
            flash("❌ 設定特佣時必須填寫開始與結束月份", "danger")
            conn.close()
            return redirect(url_for("settings.manage_products", brand=brand_code))
        cursor = conn.execute(
            "INSERT INTO SpecialCommissions (brand_code, model, start_month, end_month, rate) VALUES (?, ?, ?, ?, ?)",
            (brand_code, model, start, end, rate),
        )
        conn.commit()
        try:
            log_audit("create", "SpecialCommissions", record_id=cursor.lastrowid, new_value={"model": model, "start_month": start, "end_month": end, "rate": rate}, user=None, ip=request.remote_addr)
        except Exception:
            pass
        flash(f"✅ 已成功為 {model} 加入特佣規則 ({start} 至 {end})", "success")
    conn.close()
    return redirect(url_for("settings.manage_products", brand=brand_code))


@bp.route("/bulk_update_products", methods=["POST"])
def bulk_update_products():
    brand_code = _resolve_brand_code()
    product_ids = request.form.getlist("product_ids")
    new_rate = request.form.get("new_rate")
    if not product_ids or not new_rate:
        flash("請先勾選產品並輸入新的佣金比例！", "warning")
        return redirect(url_for("settings.manage_products", brand=brand_code))

    conn = get_db_connection()
    placeholders = ",".join("?" * len(product_ids))
    old_rows = conn.execute(
        f"SELECT * FROM Products WHERE brand_code = ? AND id IN ({placeholders})",
        [brand_code] + product_ids,
    ).fetchall()
    conn.execute(
        f"UPDATE Products SET commission_rate = ? WHERE brand_code = ? AND id IN ({placeholders})",
        [float(new_rate), brand_code] + product_ids,
    )
    conn.commit()
    new_rows = conn.execute(
        f"SELECT * FROM Products WHERE brand_code = ? AND id IN ({placeholders})",
        [brand_code] + product_ids,
    ).fetchall()
    try:
        log_audit("bulk_update", "Products", record_id=None, old_value=[dict(row) for row in old_rows], new_value=[dict(row) for row in new_rows], user=None, ip=request.remote_addr)
    except Exception:
        pass
    conn.close()
    flash(f"✅ 成功將 {len(product_ids)} 件產品的永久佣金比例更新為 {float(new_rate) * 100}%！", "success")
    return redirect(url_for("settings.manage_products", brand=brand_code))


@bp.route("/manage_locations")
def manage_locations():
    brand_code = _resolve_brand_code()
    return render_template(
        "manage_locations.html",
        locations=fetch_manage_locations_context(brand_code=brand_code),
        current_brand=brand_code,
        current_brand_name=get_brand_name(brand_code),
        available_brands=get_current_user_available_brands(),
    )


@bp.route("/manage_brands")
@admin_required
def manage_brands():
    brands = get_all_brands()
    return render_template(
        "manage_brands.html",
        brands=brands,
        default_brand_code=DEFAULT_BRAND_CODE,
    )


@bp.route("/add_brand", methods=["POST"])
@admin_required
def add_brand():
    brand_code = (request.form.get("brand_code") or "").strip().lower()
    brand_name = (request.form.get("brand_name") or "").strip()

    if not brand_code or not re.fullmatch(r"[a-z0-9_]+", brand_code):
        flash("⚠️ 品牌代碼只能包含小寫英數與底線。", "danger")
        return redirect(url_for("settings.manage_brands"))
    if not brand_name:
        flash("⚠️ 請輸入品牌名稱。", "danger")
        return redirect(url_for("settings.manage_brands"))

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO Brands (brand_code, brand_name, is_active)
            VALUES (?, ?, 1)
            """,
            (brand_code, brand_name),
        )
        conn.commit()
        try:
            log_audit(
                "create",
                "Brands",
                record_id=cursor.lastrowid,
                new_value={"brand_code": brand_code, "brand_name": brand_name, "is_active": 1},
                user=None,
                ip=request.remote_addr,
            )
        except Exception:
            pass
        flash(f"✅ 已新增品牌：{brand_name} ({brand_code})", "success")
    except sqlite3.IntegrityError:
        flash("⚠️ 品牌代碼已存在。", "danger")
    finally:
        conn.close()

    return redirect(url_for("settings.manage_brands"))


@bp.route("/update_brand", methods=["POST"])
@admin_required
def update_brand():
    brand_code = (request.form.get("brand_code") or "").strip().lower()
    brand_name = (request.form.get("brand_name") or "").strip()
    raw_is_active = request.form.get("is_active")

    if not brand_code:
        flash("⚠️ 缺少品牌代碼。", "danger")
        return redirect(url_for("settings.manage_brands"))
    if not brand_name:
        flash("⚠️ 請輸入品牌名稱。", "danger")
        return redirect(url_for("settings.manage_brands"))
    if brand_code == DEFAULT_BRAND_CODE and is_active == 0:
        flash("⚠️ 不能停用預設品牌。", "danger")
        return redirect(url_for("settings.manage_brands"))

    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Brands WHERE brand_code = ?", (brand_code,)).fetchone()
    if not old:
        conn.close()
        flash("⚠️ 找不到指定品牌。", "danger")
        return redirect(url_for("settings.manage_brands"))

    if raw_is_active in {"0", "1"}:
        is_active = 1 if raw_is_active == "1" else 0
    else:
        is_active = int(old["is_active"]) if old else 1

    conn.execute(
        "UPDATE Brands SET brand_name = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE brand_code = ?",
        (brand_name, is_active, brand_code),
    )
    conn.commit()
    new = conn.execute("SELECT * FROM Brands WHERE brand_code = ?", (brand_code,)).fetchone()
    conn.close()
    try:
        log_audit(
            "update",
            "Brands",
            record_id=brand_code,
            old_value=dict(old) if old else None,
            new_value=dict(new) if new else None,
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash("✅ 品牌設定已更新", "success")
    return redirect(url_for("settings.manage_brands"))


@bp.route("/add_location", methods=["POST"])
def add_location():
    brand_code = _resolve_brand_code()
    name = request.form.get("name").strip()
    region = request.form.get("region")
    if name:
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO Locations (brand_code, name, region) VALUES (?, ?, ?)",
                (brand_code, name, region),
            )
            conn.commit()
            try:
                log_audit("create", "Locations", record_id=cursor.lastrowid, new_value={"name": name, "region": region}, user=None, ip=request.remote_addr)
            except Exception:
                pass
            flash(f"✅ 成功新增店鋪：{name}", "success")
        except sqlite3.IntegrityError:
            flash("⚠️ 店鋪名稱已存在", "danger")
        conn.close()
    return redirect(url_for("settings.manage_locations", brand=brand_code))


@bp.route("/delete_location/<int:id>")
def delete_location(id):
    brand_code = _resolve_brand_code()
    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Locations WHERE id = ? AND brand_code = ?", (id, brand_code)).fetchone()
    conn.execute("DELETE FROM Locations WHERE id = ? AND brand_code = ?", (id, brand_code))
    conn.commit()
    conn.close()
    try:
        log_audit("delete", "Locations", record_id=id, old_value=dict(old) if old else None, user=None, ip=request.remote_addr)
    except Exception:
        pass
    flash("🗑️ 店鋪已刪除", "info")
    return redirect(url_for("settings.manage_locations", brand=brand_code))


@bp.route("/update_location", methods=["POST"])
def update_location():
    brand_code = _resolve_brand_code()
    loc_id = request.form.get("id")
    name = request.form.get("name").strip()
    region = request.form.get("region")
    if loc_id and name:
        conn = get_db_connection()
        try:
            old = conn.execute("SELECT * FROM Locations WHERE id = ? AND brand_code = ?", (loc_id, brand_code)).fetchone()
            conn.execute(
                "UPDATE Locations SET name = ?, region = ? WHERE id = ? AND brand_code = ?",
                (name, region, loc_id, brand_code),
            )
            conn.commit()
            new = conn.execute("SELECT * FROM Locations WHERE id = ? AND brand_code = ?", (loc_id, brand_code)).fetchone()
            try:
                log_audit("update", "Locations", record_id=loc_id, old_value=dict(old) if old else None, new_value=dict(new) if new else None, user=None, ip=request.remote_addr)
            except Exception:
                pass
            flash("✅ 店鋪資料已更新", "success")
        except sqlite3.IntegrityError:
            flash("⚠️ 修改失敗：店鋪名稱可能與現有重複", "danger")
        conn.close()
    return redirect(url_for("settings.manage_locations", brand=brand_code))


@bp.route("/audit_logs")
def audit_logs():
    if not is_audit_admin():
        flash("需要管理員權限才能查看稽核紀錄", "warning")
        return redirect(url_for("main.login", next=request.path))

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    table = request.args.get("table")
    action = request.args.get("action")
    user_q = request.args.get("user")
    query = request.args.get("q")

    where = []
    params = []
    if table:
        where.append("table_name = ?")
        params.append(table)
    if action:
        where.append("action = ?")
        params.append(action)
    if user_q:
        where.append("user = ?")
        params.append(user_q)
    if query:
        where.append("(record_id = ? OR timestamp LIKE ? OR old_value LIKE ? OR new_value LIKE ?)")
        params.extend([query, f"%{query}%", f"%{query}%", f"%{query}%"])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    conn = get_db_connection()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM AuditLog {where_sql}", params).fetchone()["c"]
    offset = (page - 1) * per_page
    rows = conn.execute(
        f"SELECT * FROM AuditLog {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()
    tables = [row["table_name"] for row in conn.execute("SELECT DISTINCT table_name FROM AuditLog ORDER BY table_name").fetchall()]
    actions = [row["action"] for row in conn.execute("SELECT DISTINCT action FROM AuditLog ORDER BY action").fetchall()]
    users = [row["user"] for row in conn.execute("SELECT DISTINCT user FROM AuditLog ORDER BY user").fetchall() if row["user"]]
    conn.close()

    entries = []
    for row in rows:
        entry = dict(row)
        try:
            entry["old_value_pretty"] = json.dumps(json.loads(entry["old_value"]) if entry.get("old_value") else None, ensure_ascii=False, indent=2)
        except Exception:
            entry["old_value_pretty"] = entry.get("old_value")
        try:
            entry["new_value_pretty"] = json.dumps(json.loads(entry["new_value"]) if entry.get("new_value") else None, ensure_ascii=False, indent=2)
        except Exception:
            entry["new_value_pretty"] = entry.get("new_value")
        entries.append(entry)

    return render_template(
        "audit_logs.html",
        entries=entries,
        page=page,
        per_page=per_page,
        total=total,
        table=table,
        action=action,
        user=user_q,
        q=query,
        tables=tables,
        actions=actions,
        users=users,
    )


@bp.route("/audit_logs/export")
def audit_logs_export():
    if not is_audit_admin():
        flash("需要管理員權限才能匯出稽核紀錄", "warning")
        return redirect(url_for("main.login", next=request.path))

    table = request.args.get("table")
    action = request.args.get("action")
    user_q = request.args.get("user")
    query = request.args.get("q")
    ids = request.args.get("ids")

    where = []
    params = []
    if ids:
        id_list = [item for item in ids.split(",") if item.strip().isdigit()]
        if id_list:
            placeholders = ",".join("?" * len(id_list))
            where.append(f"id IN ({placeholders})")
            params.extend(id_list)
    if table:
        where.append("table_name = ?")
        params.append(table)
    if action:
        where.append("action = ?")
        params.append(action)
    if user_q:
        where.append("user = ?")
        params.append(user_q)
    if query:
        where.append("(record_id = ? OR timestamp LIKE ? OR old_value LIKE ? OR new_value LIKE ?)")
        params.extend([query, f"%{query}%", f"%{query}%", f"%{query}%"])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    conn = get_db_connection()
    rows = conn.execute(f"SELECT * FROM AuditLog {where_sql} ORDER BY id DESC", params).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "timestamp", "user", "action", "table_name", "record_id", "old_value", "new_value", "ip"])
    for row in rows:
        values = list(row)
        writer.writerow([values[0], values[1], values[2], values[3], values[4], values[5], values[6] or "", values[7] or "", values[8] or ""])

    csv_data = output.getvalue()
    output.close()
    return (
        csv_data,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="audit_logs.csv"',
        },
    )
