from flask import Blueprint, flash, jsonify, redirect, request, url_for
from urllib.parse import parse_qs, urlparse

from app_config import DEFAULT_BRAND_CODE
from repository import fetch_sales_records, get_db_connection, set_month_input_source
from services import log_audit, resolve_brand_for_current_user

bp = Blueprint("sales", __name__)


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


@bp.route("/update_monthly_comm_api", methods=["POST"])
def update_monthly_comm_api():
    brand_code = _resolve_brand_code()
    month = request.form.get("month")
    name = request.form.get("promoter")
    comm_val = request.form.get("monthly_comm", "").strip()
    conn = get_db_connection()
    if comm_val == "":
        conn.execute(
            "UPDATE MonthlyRates SET commission_rate = NULL WHERE brand_code = ? AND payroll_month = ? AND nick_name = ?",
            (brand_code, month, name),
        )
    else:
        conn.execute(
            """
            INSERT INTO MonthlyRates (brand_code, payroll_month, nick_name, commission_rate)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(brand_code, payroll_month, nick_name) DO UPDATE SET commission_rate = excluded.commission_rate
            """,
            (brand_code, month, name, float(comm_val)),
        )
    conn.commit()
    conn.close()
    set_month_input_source(month, "web", brand_code=brand_code)
    return jsonify({"status": "success"})


@bp.route("/insert_record", methods=["POST"])
def insert_record():
    brand_code = _resolve_brand_code()
    payroll_month = request.form.get("payroll_month")
    date = request.form.get("date")
    promoter = request.form.get("promoter")
    location = request.form.get("location")
    model = request.form.get("model")
    quantity = request.form.get("quantity")
    price = request.form.get("price")

    conn = get_db_connection()
    cursor = conn.execute(
        """
        INSERT INTO Sales (brand_code, payroll_month, date, promoter_name, location, model, quantity, price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (brand_code, payroll_month, date, promoter, location, model, quantity, price),
    )
    conn.commit()
    record_id = cursor.lastrowid
    try:
        log_audit(
            "create",
            "Sales",
            record_id=record_id,
            new_value={
                "payroll_month": payroll_month,
                "date": date,
                "promoter_name": promoter,
                "location": location,
                "model": model,
                "quantity": quantity,
                "price": price,
            },
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    conn.close()
    set_month_input_source(payroll_month, "web", brand_code=brand_code)
    flash(f"成功新增一筆 {promoter} 的紀錄 ({payroll_month})！", "success")
    return redirect(url_for("main.index", month=payroll_month, brand=brand_code))


@bp.route("/delete_record/<int:record_id>", methods=["POST"])
def delete_record(record_id):
    brand_code = _resolve_brand_code()
    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Sales WHERE id = ? AND brand_code = ?", (record_id, brand_code)).fetchone()
    conn.execute("DELETE FROM Sales WHERE id = ? AND brand_code = ?", (record_id, brand_code))
    conn.commit()
    month = old["payroll_month"] if old else None
    conn.close()
    set_month_input_source(month, "web", brand_code=brand_code)
    try:
        log_audit(
            "delete",
            "Sales",
            record_id=record_id,
            old_value=dict(old) if old else None,
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash(f"紀錄 (ID: {record_id}) 已成功刪除！", "warning")
    return redirect(url_for("main.index", month=month, brand=brand_code))


@bp.route("/update_sales_record", methods=["POST"])
def update_sales_record():
    brand_code = _resolve_brand_code()
    record_id = request.form.get("id")
    date = request.form.get("date")
    model = request.form.get("model", "").strip()
    quantity = int(request.form.get("quantity", 1))
    price = float(request.form.get("price", 0.0))
    promoter_name = request.form.get("promoter_name") or request.form.get("staff_name")
    location = request.form.get("location")
    if not record_id:
        return jsonify({"status": "error", "message": "缺少記錄 ID"})

    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Sales WHERE id = ? AND brand_code = ?", (record_id, brand_code)).fetchone()
    if not old:
        conn.close()
        return jsonify({"status": "error", "message": "找不到該品牌下的銷售紀錄"})
    if model:
        conn.execute(
            "INSERT OR IGNORE INTO Products (brand_code, model, product_line) VALUES (?, ?, '未分類 (單據新增)')",
            (brand_code, model),
        )
    conn.execute(
        """
        UPDATE Sales
        SET date = ?, model = ?, quantity = ?, price = ?, promoter_name = ?, location = ?
        WHERE id = ? AND brand_code = ?
        """,
        (date, model, quantity, price, promoter_name, location, record_id, brand_code),
    )
    conn.commit()
    set_month_input_source(old["payroll_month"] if old else None, "web", brand_code=brand_code)
    new = conn.execute("SELECT * FROM Sales WHERE id = ? AND brand_code = ?", (record_id, brand_code)).fetchone()
    try:
        log_audit(
            "update",
            "Sales",
            record_id=record_id,
            old_value=dict(old) if old else None,
            new_value=dict(new) if new else None,
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    conn.close()
    return jsonify({"status": "success", "message": "已更新銷售紀錄"})


@bp.route("/api/sales_records/<month>/<nick_name>/<location>")
def get_sales_records(month, nick_name, location):
    brand_code = _resolve_brand_code()
    return jsonify(fetch_sales_records(month, nick_name, location, brand_code=brand_code))


@bp.route("/add_sales_record", methods=["POST"])
def add_sales_record():
    brand_code = _resolve_brand_code()
    month = request.form.get("payroll_month")
    name = request.form.get("promoter_name")
    date = request.form.get("date")
    location = request.form.get("location")
    model = request.form.get("model").strip()
    qty = int(request.form.get("quantity", 1))
    price = float(request.form.get("price", 0.0))

    conn = get_db_connection()
    if model:
        conn.execute(
            "INSERT OR IGNORE INTO Products (brand_code, model, product_line) VALUES (?, ?, '未分類 (單據新增)')",
            (brand_code, model),
        )
    cursor = conn.execute(
        """
        INSERT INTO Sales (brand_code, payroll_month, date, promoter_name, location, model, quantity, price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (brand_code, month, date, name, location, model, qty, price),
    )
    conn.commit()
    record_id = cursor.lastrowid
    try:
        log_audit(
            "create",
            "Sales",
            record_id=record_id,
            new_value={
                "payroll_month": month,
                "date": date,
                "promoter_name": name,
                "location": location,
                "model": model,
                "quantity": qty,
                "price": price,
            },
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    conn.close()
    set_month_input_source(month, "web", brand_code=brand_code)
    return jsonify({"status": "success", "message": "已新增銷售紀錄"})


@bp.route("/delete_sales_record/<int:id>", methods=["POST"])
def delete_sales_record(id):
    brand_code = _resolve_brand_code()
    conn = get_db_connection()
    old = conn.execute("SELECT * FROM Sales WHERE id = ? AND brand_code = ?", (id, brand_code)).fetchone()
    conn.execute("DELETE FROM Sales WHERE id = ? AND brand_code = ?", (id, brand_code))
    conn.commit()
    month = old["payroll_month"] if old else None
    conn.close()
    set_month_input_source(month, "web", brand_code=brand_code)
    try:
        log_audit(
            "delete",
            "Sales",
            record_id=id,
            old_value=dict(old) if old else None,
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    return jsonify({"status": "success", "message": "紀錄已刪除"})


@bp.route("/delete_sales_group", methods=["POST"])
def delete_sales_group():
    brand_code = _resolve_brand_code()
    month = request.form.get("month")
    promoter = request.form.get("promoter")
    location = request.form.get("location")
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM Sales WHERE brand_code = ? AND payroll_month = ? AND promoter_name = ? AND location = ?",
        (brand_code, month, promoter, location),
    ).fetchall()
    conn.execute(
        "DELETE FROM Sales WHERE brand_code = ? AND payroll_month = ? AND promoter_name = ? AND location = ?",
        (brand_code, month, promoter, location),
    )
    conn.commit()
    conn.close()
    set_month_input_source(month, "web", brand_code=brand_code)
    try:
        log_audit(
            "delete_group",
            "Sales",
            record_id=None,
            old_value=[dict(row) for row in rows],
            user=None,
            ip=request.remote_addr,
        )
    except Exception:
        pass
    flash(f"✅ 已清空 {promoter} 於 {location} 的所有單據", "success")
    return redirect(url_for("main.index", month=month, brand=brand_code))
