import re

import pandas as pd

from app_config import DEFAULT_BRAND_CODE


IMPORT_PROFILES = {
    "century_field": {
        "sheets": {
            "name_list": ["Name List"],
            "timesheet": ["工作表1"],
            "total": ["Total"],
            "sales": ["editable-sales-form"],
        },
        "headers": {
            "name_list": 1,
            "timesheet": 1,
            "sales": 1,
        },
        "columns": {
            "emp_nick_name": ["Nick Name", "Nickname", "Name"],
            "emp_hourly_rate": ["Hourly Rate", "Hourr Rate", "HourlyRate"],
            "emp_allowance": ["Allowance"],
            "emp_commission_rate": ["rate", "Rate", "Commission Rate"],
            "ts_nick_name": ["Nick Name", "Nickname", "Name"],
            "ts_date": ["Date", "Work Date"],
            "ts_location": ["Location", "Shop", "Store"],
            "ts_normal_hours": ["Normal working\n hours", "Normal Hours", "Normal working hours"],
            "ts_actual_hours": [" Hours", "Hours", "Hours Worked", "Actual Hours"],
            "ts_ot_hours": ["OT Hours", "OT hours", "Overtime", "OT"],
            "ts_in_time": ["In-Time", "In Time"],
            "ts_out_time": ["Out-Time", "Out Time"],
            "total_name": ["Name", "Nick Name", "Promoter"],
            "total_shop": ["Shop", "Location", "Store"],
            "total_attendance_bonus": ["Attendance", "Attendance Bonus"],
            "total_allowance_override": ["Allowance", "Allowance Override"],
            "total_expenses": ["Expenses", "Expense"],
            "total_adjustment": ["Adjustmant", "Adjustment"],
            "sales_promoter": ["Promoter", "Name", "Nick Name"],
            "sales_model": ["Model", "Product", "Item"],
            "sales_shop": ["Shop", "Store"],
            "sales_location": ["Location", "Area", "Branch"],
            "sales_date": ["date", "Date", "Sales Date"],
            "sales_quantity": ["quantity", "Qty", "Quantity"],
            "sales_price": ["price", "Price", "Unit Price"],
        },
    },
    "toshiba": {
        "sheets": {
            "name_list": ["Name List", "Employee List", "Staff List", "Payroll Name List"],
            "timesheet": ["工作表1", "Timesheet", "Attendance", "Attendance Report"],
            "total": ["Total", "Payroll Summary", "Summary", "Payroll Total"],
            "sales": ["editable-sales-form", "Sales", "Sales Report", "Promoter Sales Report"],
        },
        "headers": {
            "name_list": 1,
            "timesheet": 1,
            "sales": 1,
        },
        "columns": {
            "emp_nick_name": ["Nick Name", "Nickname", "Name", "Promoter"],
            "emp_hourly_rate": ["Hourly Rate", "Hourr Rate", "Rate"],
            "emp_allowance": ["Allowance"],
            "emp_commission_rate": ["rate", "Rate", "Commission Rate"],
            "ts_nick_name": ["Nick Name", "Nickname", "Name", "Promoter"],
            "ts_date": ["Date", "Work Date", "工作日期"],
            "ts_location": ["Location", "Shop", "Store", "Branch"],
            "ts_normal_hours": ["Normal working\n hours", "Normal Hours", "Regular Hours"],
            "ts_actual_hours": [" Hours", "Hours", "Hours Worked", "Actual Hours"],
            "ts_ot_hours": ["OT Hours", "OT hours", "Overtime", "OT"],
            "ts_in_time": ["In-Time", "In Time", "Clock In"],
            "ts_out_time": ["Out-Time", "Out Time", "Clock Out"],
            "total_name": ["Name", "Nick Name", "Promoter"],
            "total_shop": ["Shop", "Location", "Store", "Branch"],
            "total_attendance_bonus": ["Attendance", "Attendance Bonus"],
            "total_allowance_override": ["Allowance", "Allowance Override"],
            "total_expenses": ["Expenses", "Expense"],
            "total_adjustment": ["Adjustmant", "Adjustment"],
            "sales_promoter": ["Promoter", "Name", "Nick Name"],
            "sales_model": ["Model", "Product Model", "Item", "Product"],
            "sales_shop": ["Shop", "Store", "Branch"],
            "sales_location": ["Location", "Area", "Branch"],
            "sales_date": ["date", "Date", "Sales Date"],
            "sales_quantity": ["quantity", "Qty", "Quantity"],
            "sales_price": ["price", "Price", "Unit Price", "Amount"],
        },
    },
}


def _normalize_text(value):
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def get_import_profile(brand_code):
    key = _normalize_text(brand_code).replace(" ", "_") or DEFAULT_BRAND_CODE
    return IMPORT_PROFILES.get(key, IMPORT_PROFILES[DEFAULT_BRAND_CODE])


def pick_sheet_name(sheet_names, candidates):
    if not sheet_names:
        return None
    normalized = {_normalize_text(name): name for name in sheet_names}
    for candidate in candidates:
        key = _normalize_text(candidate)
        if key in normalized:
            return normalized[key]

    for candidate in candidates:
        key = _normalize_text(candidate)
        for sheet_name in sheet_names:
            if key in _normalize_text(sheet_name):
                return sheet_name

    return None


def read_value(row, aliases, default=None):
    if not aliases:
        return default

    for alias in aliases:
        if alias in row.index:
            value = row.get(alias)
            if value is not None and not pd.isna(value):
                return value

    normalized_index = {_normalize_text(col): col for col in row.index}
    for alias in aliases:
        col = normalized_index.get(_normalize_text(alias))
        if col is None:
            continue
        value = row.get(col)
        if value is not None and not pd.isna(value):
            return value

    return default
