import csv
import io
import os

import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

from app_config import DEFAULT_BRAND_CODE, HISTORY_FOLDER
from exporter import generate_standard_template
from importer import dispatch_import, sync_toshiba_from_api, validate_import_brand, validate_import_month
from payroll_engine import process_payroll_from_db
from repository import fetch_index_context, get_brand_name, set_month_input_source
from services import (
    authenticate_user,
    check_login_allowed,
    clear_login_failures,
    get_current_user_available_brands,
    get_request_ip,
    log_audit,
    perform_validation,
    record_login_failure,
    resolve_brand_for_current_user,
)

bp = Blueprint("main", __name__)


def normalize_next_url(next_url):
    if next_url and next_url.startswith("/"):
        return next_url
    return url_for("main.index")


def resolve_brand_code(raw_brand):
    return resolve_brand_for_current_user(raw_brand)


@bp.route("/")
def index():
    current_month = request.args.get("month", pd.Timestamp.now().strftime("%Y-%m"))
    brand_code = resolve_brand_code(request.args.get("brand"))
    payroll_results = process_payroll_from_db(current_month, brand_code=brand_code)
    context = fetch_index_context(current_month, payroll_results, brand_code=brand_code)
    return render_template(
        "index.html",
        current_month=current_month,
        current_brand=brand_code,
        current_brand_name=get_brand_name(brand_code),
        available_brands=get_current_user_available_brands(),
        staff_summary=context["staff_summary"],
        records=context["records"],
        attendances=context["attendances"],
        locations=context["locations"],
        products=context["products"],
        employees=context["employees"],
        monthly_remarks_map=context["monthly_remarks_map"],
        month_input_source=context["month_input_source"],
        has_excel_history=context["has_excel_history"],
        index_page_data={
            "currentMonth": current_month,
            "currentBrand": brand_code,
            "monthInputSource": context["month_input_source"],
        },
    )


@bp.route("/calculate_payroll", methods=["POST"])
def calculate_payroll():
    calc_month = request.form.get("calc_month")
    brand_code = resolve_brand_code(request.form.get("brand"))
    records = process_payroll_from_db(calc_month, brand_code=brand_code)
    if not records:
        flash(f"找不到 {calc_month} 的數據，請確認已輸入資料。", "danger")
        return redirect(url_for("main.index", month=calc_month, brand=brand_code))

    totals = {
        "basic": sum(row.get("底薪", 0) for row in records),
        "comm": sum(row.get("總佣金", 0) for row in records),
        "net": sum(row.get("實發薪資", 0) for row in records),
    }
    flash(f"{calc_month} 月份計算成功！", "success")
    return render_template(
        "result.html",
        records=records,
        calc_month=calc_month,
        current_brand=brand_code,
        current_brand_name=get_brand_name(brand_code),
        totals=totals,
    )


@bp.route("/view_payslip/<int:idx>/<month>")
def view_payslip(idx, month):
    brand_code = resolve_brand_code(request.args.get("brand"))
    records = process_payroll_from_db(month, brand_code=brand_code)
    if records and idx < len(records):
        return render_template(
            "payslip.html",
            emp=records[idx],
            month=month,
            current_brand=brand_code,
            current_brand_name=get_brand_name(brand_code),
        )
    flash("找不到該薪資紀錄", "danger")
    return redirect(url_for("main.index", month=month, brand=brand_code))


@bp.route("/download/<filename>")
def download_file(filename):
    return send_file(os.path.join("outputs", filename), as_attachment=True)


@bp.route("/download_payroll")
def download_payroll():
    calc_month = request.args.get("month", pd.Timestamp.now().strftime("%Y-%m"))
    brand_code = resolve_brand_code(request.args.get("brand"))
    records = process_payroll_from_db(calc_month, brand_code=brand_code)
    if not records:
        flash(f"找不到 {calc_month} 的薪資資料，請先計算！", "danger")
        return redirect(url_for("main.index", month=calc_month, brand=brand_code))

    output = io.BytesIO()
    pd.DataFrame(records).to_excel(output, index=False)
    output.seek(0)
    filename = f"Payroll_Summary_{calc_month}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/print_all/<calc_month>")
def print_all_payslips(calc_month):
    brand_code = resolve_brand_code(request.args.get("brand"))
    records = process_payroll_from_db(calc_month, brand_code=brand_code)
    if not records:
        flash(f"找不到 {calc_month} 的薪資資料，請先計算！", "danger")
        return redirect(url_for("main.index", month=calc_month, brand=brand_code))
    return render_template(
        "print_all.html",
        records=records,
        month=calc_month,
        current_brand=brand_code,
        current_brand_name=get_brand_name(brand_code),
    )


@bp.route("/validate")
def validate_data():
    current_month = request.args.get("month", pd.Timestamp.now().strftime("%Y-%m"))
    brand_code = resolve_brand_code(request.args.get("brand"))
    results = perform_validation(current_month, brand_code=brand_code)
    summary = {
        "total": len(results),
        "matched": sum(1 for row in results if "✅" in row.get("status", "")),
        "mismatched": sum(1 for row in results if "❌" in row.get("status", "")),
        "missing": sum(1 for row in results if "❓" in row.get("status", "")),
    }
    return render_template(
        "validation.html",
        results=results,
        current_month=current_month,
        current_brand=brand_code,
        current_brand_name=get_brand_name(brand_code),
        available_brands=get_current_user_available_brands(),
        summary=summary,
    )


@bp.route("/download_validation")
def download_validation():
    current_month = request.args.get("month", pd.Timestamp.now().strftime("%Y-%m"))
    brand_code = resolve_brand_code(request.args.get("brand"))
    results = perform_validation(current_month, brand_code=brand_code)

    export_cols = [
        ("month", "月份"),
        ("name", "員工"),
        ("location", "地點"),
        ("ex_basic", "Excel底薪"),
        ("sys_basic", "系統底薪"),
        ("ex_comm", "Excel佣金"),
        ("sys_comm", "系統佣金"),
        ("ex_allow", "Excel津貼"),
        ("sys_allow", "系統津貼"),
        ("ex_mpf", "Excel_MPF"),
        ("sys_mpf", "系統_MPF"),
        ("ex_net", "Excel實發"),
        ("sys_net", "系統實發"),
        ("diff", "差異($)"),
        ("mismatch_count", "差異欄位數"),
        ("mismatch_fields", "差異欄位"),
        ("root_cause", "根因提示"),
        ("status", "狀態"),
        ("sys_days", "日數"),
        ("sys_hours", "工時"),
        ("sys_ot", "OT工時"),
        ("sys_expenses", "報銷"),
        ("sys_adjustment", "微調"),
        ("sys_bonus", "出勤獎"),
        ("sys_sales_entries", "銷售筆數"),
        ("sys_sales_amount", "銷售總額"),
        ("effective_hr", "時薪"),
        ("hr_overridden", "時薪覆寫"),
        ("effective_comm_pct", "佣金率(%)"),
        ("comm_overridden", "佣金覆寫"),
    ]

    rows = []
    for r in results:
        row = {}
        for key, label in export_cols:
            val = r.get(key, "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            row[label] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    filename = f"Validation_Report_{current_month}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/upload_and_import", methods=["POST"])
def upload_and_import():
    calc_month = request.form.get("calc_month")
    brand_code = resolve_brand_code(request.form.get("brand"))
    update_emp = request.form.get("update_emp") == "on"
    if "excel_file" not in request.files:
        flash("❌ 未選擇檔案", "danger")
        return redirect(url_for("main.index", month=calc_month, brand=brand_code))

    file = request.files["excel_file"]
    if file.filename == "":
        flash("❌ 未選擇檔案", "danger")
        return redirect(url_for("main.index", month=calc_month, brand=brand_code))

    original_filename = os.path.basename(file.filename).strip()
    invalid_chars = '<>:"/\\|?*'
    original_filename = "".join("_" if ch in invalid_chars else ch for ch in original_filename).rstrip(". ")
    if not original_filename:
        flash("❌ 檔名不合法", "danger")
        return redirect(url_for("main.index", month=calc_month, brand=brand_code))

    month_key = (calc_month or pd.Timestamp.now().strftime("%Y-%m")).replace("-", "")
    archived_filename = original_filename
    if not archived_filename.startswith(month_key):
        archived_filename = f"{month_key} {archived_filename}"

    # Keep human-readable history names; same-name uploads will overwrite existing files.
    name_root, ext = os.path.splitext(archived_filename)
    if not ext:
        ext = ".xlsx"
    archived_filename = f"{name_root}{ext}"

    temp_filename = f".__uploadcheck__{archived_filename}"
    temp_file_path = os.path.join(HISTORY_FOLDER, temp_filename)
    file.save(temp_file_path)

    is_valid_brand, detected_brand, brand_error = validate_import_brand(
        temp_file_path,
        brand_code,
        original_filename=original_filename,
    )
    if not is_valid_brand:
        try:
            os.remove(temp_file_path)
        except OSError:
            pass
        flash(f"❌ {brand_error}", "danger")
        return redirect(url_for("main.index", month=calc_month, brand=brand_code))

    is_valid_month, detected_month, month_error = validate_import_month(
        temp_file_path,
        calc_month,
        original_filename=original_filename,
    )
    if not is_valid_month:
        try:
            os.remove(temp_file_path)
        except OSError:
            pass
        flash(f"❌ {month_error}", "danger")
        return redirect(url_for("main.index", month=calc_month, brand=brand_code))

    file_path = os.path.join(HISTORY_FOLDER, archived_filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    os.replace(temp_file_path, file_path)
    success, message = dispatch_import(file_path, calc_month, brand_code=brand_code, update_emp=update_emp)
    try:
        log_audit(
            "import_excel",
            "PayrollImport",
            record_id=archived_filename,
            new_value={
                "month": calc_month,
                "brand": brand_code,
                "filename": archived_filename,
                "original_filename": original_filename,
                "update_emp": bool(update_emp),
                "success": bool(success),
                "message": message,
            },
            user=session.get("user"),
            ip=get_request_ip(),
        )
    except Exception:
        pass
    if success:
        set_month_input_source(calc_month, "excel", brand_code=brand_code)
        flash("✅ 檔案已上傳至 history 並成功匯入數據！", "success")
    else:
        flash(f"⚠️ 檔案已上傳至 history 但匯入失敗: {message}", "warning")
    return redirect(url_for("main.index", month=calc_month, brand=brand_code))


@bp.route("/sync_toshiba_api", methods=["POST"])
def sync_toshiba_api():
    """從外部 API 同步 Toshiba 品牌的銷售與出勤資料。"""
    calc_month = request.form.get("calc_month")
    brand_code = resolve_brand_code(request.form.get("brand"))
    success, message = sync_toshiba_from_api(calc_month, brand_code=brand_code)
    try:
        log_audit(
            "api_sync",
            "PayrollImport",
            new_value={
                "month": calc_month,
                "brand": brand_code,
                "success": bool(success),
                "message": message,
            },
            user=session.get("user"),
            ip=get_request_ip(),
        )
    except Exception:
        pass
    if success:
        set_month_input_source(calc_month, "web", brand_code=brand_code)
        flash(message, "success")
    else:
        flash(message, "danger")
    return redirect(url_for("main.index", month=calc_month, brand=brand_code))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(request.args.get("next") or url_for("main.index"))

    if request.method == "POST":
        username = (request.form.get("user") or "").strip()
        password = request.form.get("password") or ""
        next_url = normalize_next_url(request.form.get("next") or request.args.get("next"))
        ip = get_request_ip()

        if not username or not password:
            flash("請輸入使用者名稱及密碼。", "warning")
            return render_template("login.html", next_url=next_url)

        allowed, wait_seconds = check_login_allowed(username, ip)
        if not allowed:
            wait_min = max(1, round(wait_seconds / 60))
            flash(f"登入已暫時鎖定，請約 {wait_min} 分鐘後再試。", "danger")
            try:
                log_audit(
                    "login_blocked",
                    "Auth",
                    record_id=username,
                    new_value={"username": username, "reason": "locked", "wait_seconds": wait_seconds},
                    user=username,
                    ip=ip,
                )
            except Exception:
                pass
            return render_template("login.html", next_url=next_url)

        user = authenticate_user(username, password)
        if not user:
            locked_now, _ = record_login_failure(username, ip)
            flash("登入失敗：帳號或密碼不正確。", "danger")
            try:
                log_audit(
                    "login_failed",
                    "Auth",
                    record_id=username,
                    new_value={"username": username, "locked": bool(locked_now)},
                    user=username,
                    ip=ip,
                )
            except Exception:
                pass
            return render_template("login.html", next_url=next_url)

        clear_login_failures(username, ip)
        session["user"] = user["username"]
        session["is_admin"] = bool(user["is_admin"])
        try:
            log_audit(
                "login_success",
                "Auth",
                record_id=username,
                new_value={"username": username},
                user=username,
                ip=ip,
            )
        except Exception:
            pass
        flash(f"歡迎，{user['username']}", "success")
        return redirect(next_url)

    return render_template("login.html", next_url=normalize_next_url(request.args.get("next")))


@bp.route("/logout")
def logout():
    session.clear()
    flash("已登出", "info")
    return redirect(url_for("main.index"))


# 貼在 main.py 裡面
@bp.route("/download_standard_template")
def download_standard_template():
    calc_month = request.args.get("month", pd.Timestamp.now().strftime("%Y-%m"))
    brand_code = resolve_brand_code(request.args.get("brand"))
    
    # 呼叫剛才寫的函數
    filepath = generate_standard_template(calc_month, brand_code=brand_code)
    
    filename = os.path.basename(filepath)
    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
