import sqlite3
import pandas as pd
import math
import re

from app_config import SUPPORTED_BRANDS
from brand_profiles import get_import_profile, pick_sheet_name, read_value

def get_db_connection():
    conn = sqlite3.connect('payroll.db')
    conn.row_factory = sqlite3.Row
    return conn

# 🌟 新增：終極字串淨化函數 (殺死所有隱形空格與多餘空白)
def clean_text(text, is_name=False):
    if pd.isna(text) or text is None:
        return ""
    text_str = str(text)
    if text_str.strip().lower() == 'nan':
        return ""
    
    # 核心魔法：把所有的全形空白、tab、連續多個空白，通通替換成一個標準的半形空白，然後去頭去尾
    cleaned = re.sub(r'\s+', ' ', text_str).strip()
    
    # 如果是人名，強制把每個單字字首大寫 (apple -> Apple, irene -> Irene)
    if is_name and cleaned:
        return cleaned.title()
    return cleaned


def is_usable_name(name):
    """Basic name sanity check used for source sheets (not strict human-name validation)."""
    cleaned = clean_text(name, is_name=True)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in {"nan", "none", "null", "0", "0.0"}:
        return False
    if lowered in {"列標籤", "總計", "total", "subtotal", "grand total", "model-input-ref2"}:
        return False
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", cleaned):
        return False
    return True


def is_valid_nick_name(name):
    """Stricter legacy guard for generic imports (Century and non-Total flows)."""
    cleaned = clean_text(name, is_name=True)
    if not is_usable_name(cleaned):
        return False
    # Reject purely numeric nick names (e.g. "0", "123", "12.5").
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", cleaned):
        return False
    # Reject compact alphanumeric SKU-like tokens without spaces/underscores
    # (e.g. Cfk01W75). Keep len threshold to avoid false positives.
    if " " not in cleaned and "_" not in cleaned:
        letters = sum(ch.isalpha() for ch in cleaned)
        digits = sum(ch.isdigit() for ch in cleaned)
        if len(cleaned) >= 6 and letters >= 2 and digits >= 2:
            return False
    # Reject obvious model-like codes (e.g. RC-18AMXH(W), GR-RM469WE-PGA(B3)).
    # Valid nick names in this project may include underscore/digits, but typically
    # not long hyphenated SKU-like patterns with digits and optional parentheses.
    if "-" in cleaned and any(ch.isdigit() for ch in cleaned):
        compact = cleaned.replace("-", "")
        letters = sum(ch.isalpha() for ch in compact)
        digits = sum(ch.isdigit() for ch in compact)
        if letters >= 2 and digits >= 1:
            return False
    return True


def _looks_like_toshiba_payroll(file_path, sheet_names):
    if "工作表3" in sheet_names:
        try:
            df_peek3 = pd.read_excel(file_path, sheet_name="工作表3", header=0, nrows=1)
            cols_lower = {str(c).strip().lower() for c in df_peek3.columns}
            if "days" in cols_lower or "reg.hrs" in cols_lower or "reg hrs" in cols_lower:
                return True
        except Exception:
            pass

    if "工作表1" in sheet_names:
        try:
            df_peek1 = pd.read_excel(file_path, sheet_name="工作表1", header=0, nrows=1)
            cols_lower = {str(c).strip().lower() for c in df_peek1.columns}
            if "name1" in cols_lower and ("$$$" in cols_lower or "%" in cols_lower):
                return True
        except Exception:
            pass

    return False


def _looks_like_toshiba_sales(file_path, sheet_names):
    matching_sheets = 0
    for sh in sheet_names:
        try:
            df_peek = pd.read_excel(file_path, sheet_name=sh, header=0, nrows=1)
            if _is_sales_sheet(df_peek):
                matching_sheets += 1
        except Exception:
            continue

    if matching_sheets >= 2:
        return True
    if matching_sheets >= 1 and "editable-sales-form" not in sheet_names:
        return True
    return False


def detect_import_brand(file_path, original_filename=""):
    """只根據檔名進行品牌辨識，不開啟 Excel 內容"""
    # 確保檔名存在並轉為小寫
    filename = str(original_filename or file_path).lower()
    
    # 1. 取得資料庫中最新的品牌對照表
    supported_brands = get_supported_brands_from_db()
    
    # 2. 僅掃描檔名關鍵字
    for brand_code, brand_name in supported_brands.items():
        name_lower = brand_name.lower()          
        code_lower = brand_code.lower()          
        code_space = code_lower.replace("_", " ")
        
        # [精確比對] 檔名包含完整名稱或代碼
        if name_lower in filename or code_lower in filename or code_space in filename:
            return brand_code
            
        # [模糊比對] 針對多單字品牌，取第一個單字作為關鍵字
        first_word = name_lower.split()[0]
        if len(first_word) >= 4 and first_word in filename:
            return brand_code

    # 如果檔名怎麼寫都沒命中，回傳 None (代表不阻擋，直接信任使用者選擇的品牌)
    return None

def get_supported_brands_from_db():
    """
    從資料庫的 brand 資料表中動態讀取所有支援的品牌
    回傳字典格式，例如：{'toshiba': 'Toshiba', 'ecovacs': 'Ecovacs'}
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 假設你的 brand 資料表欄位為 brand_code 與 brand_name
        # (請根據你資料庫中實際的欄位名稱調整，例如 code / name)
        cursor.execute("SELECT brand_code, brand_name FROM brand")
        rows = cursor.fetchall()
        
        # 將每一行轉為字典的 key-value 對
        # 因為使用了 sqlite3.Row，可以直接用欄位名稱存取
        return {row['brand_code']: row['brand_name'] for row in rows}
    except sqlite3.OperationalError as e:
        # 預防資料表不存在或欄位不對時程式崩潰，提供安全備份
        print(f"資料庫讀取品牌失敗: {e}")
        return {}
    finally:
        conn.close()

def validate_import_brand(file_path, selected_brand_code, original_filename=""):
    detected_brand = detect_import_brand(file_path, original_filename=original_filename)
    if not detected_brand:
        return True, None, None
    if detected_brand == selected_brand_code:
        return True, detected_brand, None

    # 🌟 改為從資料庫動態獲取最新的品牌對照表
    supported_brands = get_supported_brands_from_db()

    # 取得顯示名稱（若資料庫中找不到，則以代碼當作預設值）
    detected_name = supported_brands.get(detected_brand, detected_brand)
    selected_name = supported_brands.get(selected_brand_code, selected_brand_code)
    
    return False, detected_brand, f"上傳檔案辨識為 {detected_name}，與目前選擇的品牌 {selected_name} 不一致，已阻止匯入。"

def _normalize_header_name(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _extract_month_from_text(text):
    value = str(text or "")
    match = re.search(r"(?<!\d)(20\d{2})[-_\s/]?(0[1-9]|1[0-2])(?!\d)", value)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _extract_month_from_dataframe(df, aliases):
    if df is None or df.empty:
        return None

    normalized_columns = {_normalize_header_name(col): col for col in df.columns}
    source_col = None
    for alias in aliases:
        source_col = normalized_columns.get(_normalize_header_name(alias))
        if source_col is not None:
            break
    if source_col is None:
        return None

    parsed = pd.to_datetime(df[source_col], errors="coerce")
    parsed = parsed.dropna()
    if parsed.empty:
        return None

    month_counts = parsed.dt.strftime("%Y-%m").value_counts()
    return month_counts.index[0] if not month_counts.empty else None


def detect_import_month(file_path, original_filename=""):
    detected_from_name = _extract_month_from_text(original_filename or file_path)
    if detected_from_name:
        return detected_from_name

    try:
        workbook = pd.ExcelFile(file_path)
        sheet_names = workbook.sheet_names
    except Exception:
        return None

    # Century / generic timesheet
    if "工作表1" in sheet_names:
        for header_row in (1, 0):
            try:
                df_timesheet = pd.read_excel(file_path, sheet_name="工作表1", header=header_row, nrows=300)
                detected = _extract_month_from_dataframe(df_timesheet, ["Date", "Work Date", "工作日期"])
                if detected:
                    return detected
            except Exception:
                pass

    # Century sales sheet
    if "editable-sales-form" in sheet_names:
        try:
            df_sales = pd.read_excel(file_path, sheet_name="editable-sales-form", header=1, nrows=300)
            detected = _extract_month_from_dataframe(df_sales, ["date", "Date", "Sales Date"])
            if detected:
                return detected
        except Exception:
            pass

    # Toshiba sales report sheets
    for sh in sheet_names:
        try:
            df_peek = pd.read_excel(file_path, sheet_name=sh, header=0, nrows=50)
            if _is_sales_sheet(df_peek):
                detected = _extract_month_from_dataframe(df_peek, ["date", "Date"])
                if detected:
                    return detected
        except Exception:
            continue

    return None


def validate_import_month(file_path, selected_month, original_filename=""):
    detected_month = detect_import_month(file_path, original_filename=original_filename)
    if not detected_month or not selected_month:
        return True, None, None
    if detected_month == selected_month:
        return True, detected_month, None
    return False, detected_month, f"上傳檔案辨識月份為 {detected_month}，與目前選擇的月份 {selected_month} 不一致，已阻止匯入。"

def process_excel_import(file_path, payroll_month, brand_code="century_field", update_emp=True):
    """
    從 Excel 匯入單月資料的核心邏輯
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        profile = get_import_profile(brand_code)
        columns = profile["columns"]
        sheet_names = pd.ExcelFile(file_path).sheet_names

        # ==========================================
        # A. 處理員工名單 (Name List) - 🌟 增加判斷開關
        # ==========================================
        if update_emp:
            name_list_sheet = pick_sheet_name(sheet_names, profile["sheets"]["name_list"])
            if name_list_sheet:
                emp_df = pd.read_excel(file_path, sheet_name=name_list_sheet, header=profile["headers"]["name_list"])
            else:
                emp_df = pd.DataFrame()

            for _, row in emp_df.iterrows():
                nick_name = clean_text(read_value(row, columns["emp_nick_name"]), is_name=True)
                if not is_valid_nick_name(nick_name):
                    continue
                
                h_rate = float(pd.to_numeric(read_value(row, columns["emp_hourly_rate"], 0), errors='coerce') or 0.0)
                allowance = float(pd.to_numeric(read_value(row, columns["emp_allowance"], 0), errors='coerce') or 0.0)

                # 讀取佣金比例：清理 "3%%" 之類的格式錯誤
                raw_comm = read_value(row, columns["emp_commission_rate"], None)
                comm_rate = 0.03  # 預設值
                if raw_comm is not None and not pd.isna(raw_comm):
                    comm_str = str(raw_comm).strip().replace('%', '')
                    try:
                        comm_val = float(comm_str)
                        # 若輸入的是百分比整數 (e.g. 3 代表 3%)，自動轉換
                        comm_rate = comm_val / 100.0 if comm_val > 1 else comm_val
                    except ValueError:
                        comm_rate = 0.03

                # 新員工：建立 Employees 記錄（不覆蓋既有員工的全域預設時薪）
                cursor.execute('''
                    INSERT INTO Employees (brand_code, nick_name, hourly_rate, allowance, commission_rate) 
                    VALUES (?, ?, ?, ?, 0.03)
                    ON CONFLICT(brand_code, nick_name) DO NOTHING
                ''', (brand_code, nick_name, h_rate, allowance))

                # 把本月時薪/津貼/佣金比例寫入 MonthlyRates（月度覆蓋，不影響其他月份）
                cursor.execute('''
                    INSERT INTO MonthlyRates (brand_code, payroll_month, nick_name, hourly_rate, allowance, commission_rate)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(brand_code, payroll_month, nick_name) DO UPDATE SET
                        hourly_rate = excluded.hourly_rate,
                        allowance = excluded.allowance,
                        commission_rate = excluded.commission_rate
                ''', (brand_code, payroll_month, nick_name, h_rate, allowance, comm_rate))

        # ==========================================
        # B & C. 處理考勤明細 (工作表1) 並彙總至 Attendance
        # ==========================================
        cursor.execute("DELETE FROM DailyAttendance WHERE brand_code = ? AND payroll_month = ?", (brand_code, payroll_month))
        cursor.execute("DELETE FROM Attendance WHERE brand_code = ? AND payroll_month = ?", (brand_code, payroll_month))

        timesheet_sheet = pick_sheet_name(sheet_names, profile["sheets"]["timesheet"])
        if not timesheet_sheet:
            raise ValueError("找不到考勤分頁，請檢查模板或品牌設定。")
        df_timesheet = pd.read_excel(file_path, sheet_name=timesheet_sheet, header=profile["headers"]["timesheet"])
        
        # 用於存放「每人、每店」的月結加總
        monthly_att = {}

        for _, row in df_timesheet.iterrows():
            nick_name = clean_text(read_value(row, columns["ts_nick_name"]))
            if not is_valid_nick_name(nick_name):
                continue

            work_date = pd.to_datetime(read_value(row, columns["ts_date"]), errors='coerce')
            if pd.isna(work_date):
                continue
            
            loc = clean_text(read_value(row, columns["ts_location"]))
            if loc:
                cursor.execute(
                    "INSERT OR IGNORE INTO Locations (brand_code, name, region) VALUES (?, ?, 'Excel匯入')",
                    (brand_code, loc),
                )
            
            # 抓取工時欄位
            normal_h = float(pd.to_numeric(read_value(row, columns["ts_normal_hours"], 0), errors='coerce') or 0)
            actual_h = float(pd.to_numeric(read_value(row, columns["ts_actual_hours"], 0), errors='coerce') or 0)
            raw_ot_h = float(pd.to_numeric(read_value(row, columns["ts_ot_hours"], 0), errors='coerce') or 0)
            
            # 🌟 OT 半小時進位淨化規則
            clean_ot_h = 0.0
            if raw_ot_h >= 0.5:
                clean_ot_h = math.floor(raw_ot_h / 0.5) * 0.5
            
            # 底薪工時 = 實際總工時 - 原始 OT
            payable_normal = actual_h - raw_ot_h

            # 1. 寫入 DailyAttendance
            cursor.execute('''
                INSERT INTO DailyAttendance (brand_code, payroll_month, work_date, nick_name, location, in_time, out_time, normal_hours, actual_hours, ot_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                brand_code,
                payroll_month,
                work_date.strftime('%Y-%m-%d'),
                nick_name,
                loc,
                str(read_value(row, columns["ts_in_time"], '')),
                str(read_value(row, columns["ts_out_time"], '')),
                  normal_h, actual_h, clean_ot_h))

            # 2. 累計總數
            key = (nick_name, loc)
            if key not in monthly_att:
                monthly_att[key] = {'days': 0, 'hours': 0.0, 'ot': 0.0}
            monthly_att[key]['days'] += 1
            monthly_att[key]['hours'] += payable_normal
            monthly_att[key]['ot'] += clean_ot_h

        # 寫入 Attendance 總表
        for (nick_name, loc), totals in monthly_att.items():
            cursor.execute('''
                INSERT INTO Attendance (brand_code, payroll_month, nick_name, location, days_worked, hours, ot_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(brand_code, payroll_month, nick_name, location) DO UPDATE SET
                    days_worked = excluded.days_worked,
                    hours = excluded.hours,
                    ot_hours = excluded.ot_hours
            ''', (brand_code, payroll_month, nick_name, loc, totals['days'], totals['hours'], totals['ot']))

        # ==========================================
        # D. 從 Total 分頁抄寫 4 大金錢欄位
        # ==========================================
        try:
            total_sheet = pick_sheet_name(sheet_names, profile["sheets"]["total"])
            if not total_sheet:
                raise ValueError("找不到 Total 分頁")

            total_raw = pd.read_excel(file_path, sheet_name=total_sheet, header=None)
            header_idx = None
            for idx, row_data in total_raw.iterrows():
                row_strs = [str(x).strip().lower() for x in row_data.values]
                if 'name' in row_strs and ('total' in row_strs or 'basic' in row_strs):
                    header_idx = idx
                    break

            if header_idx is not None:
                total_df = pd.read_excel(file_path, sheet_name=total_sheet, header=header_idx)
                for _, row in total_df.iterrows():
                    name = clean_text(read_value(row, columns["total_name"]))
                    if not is_valid_nick_name(name):
                        continue
                    shop = clean_text(read_value(row, columns["total_shop"], ''))
                    
                    # 抓取指定 4 欄
                    att_bonus = float(pd.to_numeric(read_value(row, columns["total_attendance_bonus"], 0), errors='coerce') or 0.0)
                    allowance_ov = float(pd.to_numeric(read_value(row, columns["total_allowance_override"], 0), errors='coerce') or 0.0)
                    expenses = float(pd.to_numeric(read_value(row, columns["total_expenses"], 0), errors='coerce') or 0.0)
                    adj = float(pd.to_numeric(read_value(row, columns["total_adjustment"], 0), errors='coerce') or 0.0)

                    if any(v != 0 for v in [att_bonus, allowance_ov, expenses, adj]):
                        cursor.execute('''
                            UPDATE Attendance 
                            SET attendance_bonus = ?, allowance_override = ?, expenses = ?, adjustment = ?
                            WHERE brand_code = ? AND payroll_month = ? AND nick_name = ? AND location LIKE ?
                        ''', (att_bonus, allowance_ov, expenses, adj, brand_code, payroll_month, name, f"%{shop}%"))
        except Exception as e:
            print(f"Total 分頁讀取異常: {e}")

        # ==========================================
        # E. 處理銷售紀錄
        # ==========================================
        cursor.execute("DELETE FROM Sales WHERE brand_code = ? AND payroll_month = ?", (brand_code, payroll_month))
        sales_sheet = pick_sheet_name(sheet_names, profile["sheets"]["sales"])
        if sales_sheet:
            sales_df = pd.read_excel(file_path, sheet_name=sales_sheet, header=profile["headers"]["sales"])
            for _, row in sales_df.iterrows():
                promoter = clean_text(read_value(row, columns["sales_promoter"]))
                if promoter.lower() in ['nan', '0', '']:
                    continue

                shop = clean_text(read_value(row, columns["sales_shop"], ''))
                location = clean_text(read_value(row, columns["sales_location"], ''))
                loc = f"{shop} {location}".strip()
                model = clean_text(read_value(row, columns["sales_model"]))
                if not model:
                    continue

                quantity = int(pd.to_numeric(read_value(row, columns["sales_quantity"], 1), errors='coerce') or 1)
                price = float(pd.to_numeric(read_value(row, columns["sales_price"], 0), errors='coerce') or 0)
                sales_date = str(read_value(row, columns["sales_date"], ''))

                cursor.execute(
                    "INSERT OR IGNORE INTO Products (brand_code, model, product_line) VALUES (?, ?, '未分類')",
                    (brand_code, model),
                )
                cursor.execute('''
                    INSERT INTO Sales (brand_code, payroll_month, date, promoter_name, location, model, quantity, price)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (brand_code, payroll_month, sales_date, promoter, loc, model, quantity, price))

        conn.commit()
        return True, "✅ 匯入成功：員工時薪、工時總計與微調已同步更新。"
    except Exception as e:
        conn.rollback()
        return False, f"❌ 匯入失敗: {str(e)}"
    finally:
        conn.close()


# ==============================================================================
# Toshiba 專用匯入函數
#
# 支援兩種 Toshiba Excel 檔案（可分開兩次上傳）：
#
# 1. Payroll 檔 (e.g. ToshibaAC Payroll (ALL).xlsx)
#    - 工作表1 (header=0)：員工清單，欄位 Name1, $$$, Allowance, %
#    - 工作表3 (header=0)：月結考勤摘要，欄位 Name., Shop, Days, Reg.Hrs, $, Allowance
#      ★ Toshiba 格式無每日打卡明細，直接寫入 Attendance 月結表，不填 DailyAttendance
#
# 2. Sales Report 檔 (e.g. Toshiba Promoter Sales Report.xlsx)
#    - 各分店 sheet (Yata / Suning / Broadway / ...)：
#      欄位 Shop, Location, promoter, date, model, qty, price
#    - 函數自動偵測含 promoter + model + qty 欄位的 sheet 作為銷售資料
# ==============================================================================


def _is_sales_sheet(df):
    """判斷 DataFrame 是否為 Toshiba 分店銷售 sheet（含 promoter/model/qty 欄）"""
    cols_lower = {str(c).strip().lower() for c in df.columns}
    return "promoter" in cols_lower and "model" in cols_lower and "qty" in cols_lower


def _extract_total_names(file_path, total_sheet_name):
    """Extract valid employee names from Payroll Total sheet as source of truth."""
    names = set()
    total_raw = pd.read_excel(file_path, sheet_name=total_sheet_name, header=None)

    header_idx = None
    for idx, row_data in total_raw.iterrows():
        row_strs = [str(x).strip().lower() for x in row_data.values]
        if "name" in row_strs or "nick name" in row_strs or "promoter" in row_strs:
            header_idx = idx
            break

    if header_idx is not None:
        total_df = pd.read_excel(file_path, sheet_name=total_sheet_name, header=header_idx)
    else:
        total_df = pd.read_excel(file_path, sheet_name=total_sheet_name, header=0)

    for _, row in total_df.iterrows():
        candidate = clean_text(
            read_value(row, ["Name", "Nick Name", "Promoter", "Name.", "Name1", "姓名"], ""),
            is_name=True,
        )
        if is_usable_name(candidate):
            names.add(candidate)

    return names


def process_toshiba_import(file_path, payroll_month, brand_code="toshiba", update_emp=True):
    """
    Toshiba 專用匯入函數。
    自動偵測上傳的是 Payroll 檔還是 Sales Report 檔，並分別處理。
    兩個檔案可以按任何順序分兩次上傳，互不覆蓋對方的資料。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        sheet_names = pd.ExcelFile(file_path).sheet_names
        profile = get_import_profile(brand_code)
        imported_parts = []

        # ── 偵測檔案類型 ──────────────────────────────────────────────────────
        # Payroll 檔的工作表3 必須含有 Days 和 Reg.Hrs 欄位，
        # 避免 Sales Report 檔裡的同名 pivot-table sheet 被誤判
        is_payroll_file = False
        if "工作表3" in sheet_names:
            try:
                df_peek3 = pd.read_excel(file_path, sheet_name="工作表3", header=0, nrows=1)
                cols_lower = {str(c).strip().lower() for c in df_peek3.columns}
                if "days" in cols_lower or "reg.hrs" in cols_lower or "reg hrs" in cols_lower:
                    is_payroll_file = True
            except Exception:
                pass

        # 逐 sheet 嘗試讀 1 行，看是否符合銷售 sheet 格式
        sales_sheets = []
        for sh in sheet_names:
            try:
                df_peek = pd.read_excel(file_path, sheet_name=sh, header=0, nrows=1)
                if _is_sales_sheet(df_peek):
                    sales_sheets.append(sh)
            except Exception:
                pass

        if not is_payroll_file and not sales_sheets:
            raise ValueError(
                "無法識別 Toshiba Excel 格式。\n"
                "請確認上傳的是：\n"
                "  1. Payroll 檔（含「工作表3」sheet），或\n"
                "  2. Sales Report 檔（含 Shop/promoter/model/qty 欄位的分店 sheet）"
            )

        # ==========================================
        # PAYROLL 檔：工作表1 + 工作表3
        # ==========================================
        if is_payroll_file:
            total_sheet = pick_sheet_name(sheet_names, profile["sheets"]["total"])
            if not total_sheet:
                raise ValueError("Toshiba Payroll 匯入失敗：找不到 Total sheet，無法建立員工依據。")

            total_names = _extract_total_names(file_path, total_sheet)
            if not total_names:
                raise ValueError("Toshiba Payroll 匯入失敗：Total sheet 沒有可用員工名單。")

            # Step A：從工作表1 建立對照表（Name1 → 佣金率/時薪）
            comm_map = {}
            hourly_map = {}
            try:
                df1 = pd.read_excel(file_path, sheet_name="工作表1", header=0)
                for _, row in df1.iterrows():
                    # Name1 欄是 Toshiba 的 nick name（對應工作表3 的 Name. 欄）
                    name1 = clean_text(read_value(row, ["Name1"], ""), is_name=True)
                    if name1 not in total_names:
                        continue
                    raw_hourly = read_value(row, ["$$$", "$", "Hourly Rate", "Rate"], None)
                    if raw_hourly is not None and not pd.isna(raw_hourly):
                        try:
                            hourly_map[name1] = float(pd.to_numeric(raw_hourly, errors="coerce") or 0.0)
                        except (ValueError, TypeError):
                            pass
                    raw_pct = read_value(row, ["%"], None)
                    if raw_pct is not None and not pd.isna(raw_pct):
                        try:
                            v = float(str(raw_pct).strip().replace("%", ""))
                            comm_map[name1] = v / 100.0 if v > 1 else v
                        except (ValueError, TypeError):
                            comm_map[name1] = 0.02  # Toshiba 預設佣金 2%
            except Exception as e:
                print(f"Toshiba 工作表1 讀取異常（佣金率對照）: {e}")

            # Step B：清除本月考勤資料（重新匯入）
            cursor.execute(
                "DELETE FROM DailyAttendance WHERE brand_code = ? AND payroll_month = ?",
                (brand_code, payroll_month),
            )
            cursor.execute(
                "DELETE FROM Attendance WHERE brand_code = ? AND payroll_month = ?",
                (brand_code, payroll_month),
            )

            # Step C：從工作表3 讀取月結考勤，直接寫入 Attendance（無每日明細）
            df3 = pd.read_excel(file_path, sheet_name="工作表3", header=0)
            for _, row in df3.iterrows():
                nick_name = clean_text(read_value(row, ["Name.", "Name"], ""), is_name=True)
                # Employee source of truth: only names listed in Payroll Total sheet.
                if nick_name not in total_names:
                    continue

                loc = clean_text(read_value(row, ["Shop", "Location"], ""))
                if loc in {"0", "0.0"}:
                    continue
                days  = int(pd.to_numeric(read_value(row, ["Days"], 0), errors="coerce") or 0)
                hours = float(pd.to_numeric(read_value(row, ["Reg.Hrs", "Reg. Hrs", "Reg Hrs"], 0), errors="coerce") or 0)
                h_rate = float(pd.to_numeric(read_value(row, ["$"], 0), errors="coerce") or 0)
                # Toshiba 有些列在工作表3 的 "$" 會是 0，改以工作表1 的 "$$$" 作 fallback。
                if h_rate <= 0:
                    h_rate = float(hourly_map.get(nick_name, 0.0) or 0.0)
                # 工作表3 的 Allowance 欄是月度津貼總額（e.g. 30/day × 22 days = 660）
                monthly_allowance = float(pd.to_numeric(read_value(row, ["Allowance"], 0), errors="coerce") or 0)
                comm_rate = comm_map.get(nick_name, 0.02)

                # 建立 Location 記錄
                if loc:
                    cursor.execute(
                        "INSERT OR IGNORE INTO Locations (brand_code, name, region) VALUES (?, ?, 'Excel匯入')",
                        (brand_code, loc),
                    )

                # 建立 / 更新 Employees（不覆蓋既有員工的全域設定）
                if update_emp:
                    cursor.execute(
                        """
                        INSERT INTO Employees (brand_code, nick_name, hourly_rate, allowance, commission_rate)
                        VALUES (?, ?, ?, 0, ?)
                        ON CONFLICT(brand_code, nick_name) DO NOTHING
                        """,
                        (brand_code, nick_name, h_rate, comm_rate),
                    )
                    # MonthlyRates：儲存本月時薪、月津貼總額與佣金率
                    cursor.execute(
                        """
                        INSERT INTO MonthlyRates (brand_code, payroll_month, nick_name, hourly_rate, allowance, commission_rate)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(brand_code, payroll_month, nick_name) DO UPDATE SET
                            hourly_rate = excluded.hourly_rate,
                            allowance = excluded.allowance,
                            commission_rate = excluded.commission_rate
                        """,
                        (brand_code, payroll_month, nick_name, h_rate, monthly_allowance, comm_rate),
                    )

                # Attendance：月結摘要，ot_hours=0（Toshiba 格式無 OT 欄），
                # allowance_override 存月津貼總額供 payroll_engine 使用
                cursor.execute(
                    """
                    INSERT INTO Attendance
                        (brand_code, payroll_month, nick_name, location,
                         days_worked, hours, ot_hours, allowance_override)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(brand_code, payroll_month, nick_name, location) DO UPDATE SET
                        days_worked       = excluded.days_worked,
                        hours             = excluded.hours,
                        ot_hours          = 0,
                        allowance_override = excluded.allowance_override
                    """,
                    (brand_code, payroll_month, nick_name, loc, days, hours, monthly_allowance),
                )

            imported_parts.append("考勤月結")

        # ==========================================
        # SALES REPORT 檔：各分店 sheet
        # ==========================================
        if sales_sheets:
            # 只清除本月銷售（不影響考勤資料）
            cursor.execute(
                "DELETE FROM Sales WHERE brand_code = ? AND payroll_month = ?",
                (brand_code, payroll_month),
            )
            for sh in sales_sheets:
                df_sales = pd.read_excel(file_path, sheet_name=sh, header=0)
                for _, row in df_sales.iterrows():
                    promoter = clean_text(read_value(row, ["promoter", "Promoter", "Name"], ""))
                    if promoter.lower() in ["nan", "0", ""]:
                        continue
                    model = clean_text(read_value(row, ["model", "Model"], ""))
                    if not model:
                        continue

                    shop     = clean_text(read_value(row, ["Shop", "Store"], ""))
                    location = clean_text(read_value(row, ["Location", "Area"], ""))
                    loc = f"{shop} {location}".strip() if location else shop

                    qty        = int(pd.to_numeric(read_value(row, ["qty", "Qty", "Quantity"], 1), errors="coerce") or 1)
                    price      = float(pd.to_numeric(read_value(row, ["price", "Price"], 0), errors="coerce") or 0)
                    sale_date  = str(read_value(row, ["date", "Date"], ""))

                    cursor.execute(
                        "INSERT OR IGNORE INTO Products (brand_code, model, product_line) VALUES (?, ?, '未分類')",
                        (brand_code, model),
                    )
                    cursor.execute(
                        """
                        INSERT INTO Sales
                            (brand_code, payroll_month, date, promoter_name, location, model, quantity, price)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (brand_code, payroll_month, sale_date, promoter, loc, model, qty, price),
                    )

            imported_parts.append(f"銷售紀錄（{len(sales_sheets)} 個分店 sheet）")

        conn.commit()
        return True, f"✅ Toshiba 匯入成功：{'、'.join(imported_parts)}已更新。"
    except Exception as e:
        conn.rollback()
        return False, f"❌ Toshiba 匯入失敗: {str(e)}"
    finally:
        conn.close()


def dispatch_import(file_path, payroll_month, brand_code="century_field", update_emp=True):
    """
    根據 brand_code 路由至對應的匯入函數。
    新增品牌時，在此加一個 elif 分支即可。
    """
    if brand_code == "toshiba":
        return process_toshiba_import(file_path, payroll_month, brand_code=brand_code, update_emp=update_emp)
    # 其他品牌（包含 century_field）走通用版
    return process_excel_import(file_path, payroll_month, brand_code=brand_code, update_emp=update_emp)


# ==============================================================================
# Toshiba API 同步（外部數據管理系統 → 本機 SQLite）
# ==============================================================================

def sync_toshiba_from_api(payroll_month, brand_code="toshiba"):
    """從外部 API 同步 Toshiba 品牌的銷售與出勤資料。

    不走 Excel，直接呼叫 API_SUMMARY.md 描述的 port 5000 API，
    將銷售 / 出勤 / 員工資料寫入 SQLite 的 Sales、DailyAttendance、Attendance 表。

    Args:
        payroll_month: 計薪月份，格式 "YYYY-MM"
        brand_code: 品牌代碼，固定為 toshiba

    Returns:
        (success: bool, message: str)
    """
    from external_api.api_client import ExternalAPIClient
    from external_api.transforms import (
        transform_duty_report,
        transform_profile_report,
        transform_sales_report,
    )

    client = ExternalAPIClient()
    conn = get_db_connection()
    cursor = conn.cursor()
    imported_parts = []

    try:
        # ── 1. 員工資料 ─────────────────────────────────────────────
        try:
            profile_data = client.get_report("profile")
            emp_rows = transform_profile_report(profile_data, brand_code)
            for emp in emp_rows:
                cursor.execute(
                    """
                    INSERT INTO Employees (brand_code, nick_name, full_name, hourly_rate, allowance, commission_rate, salary_type, monthly_salary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(brand_code, nick_name) DO UPDATE SET
                        full_name          = COALESCE(excluded.full_name, Employees.full_name),
                        hourly_rate        = COALESCE(NULLIF(excluded.hourly_rate, 0), Employees.hourly_rate),
                        allowance          = COALESCE(NULLIF(excluded.allowance, 0), Employees.allowance),
                        commission_rate    = COALESCE(NULLIF(excluded.commission_rate, 0), Employees.commission_rate),
                        salary_type        = COALESCE(NULLIF(excluded.salary_type, ''), Employees.salary_type),
                        monthly_salary     = COALESCE(NULLIF(excluded.monthly_salary, 0), Employees.monthly_salary)
                    """,
                    (brand_code, emp["nick_name"], emp["full_name"], emp["hourly_rate"],
                     emp["allowance"], emp["commission_rate"], emp["salary_type"], emp["monthly_salary"]),
                )
                # 同步 MonthlyRates
                cursor.execute(
                    """
                    INSERT INTO MonthlyRates (brand_code, payroll_month, nick_name, hourly_rate, allowance, commission_rate)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(brand_code, payroll_month, nick_name) DO UPDATE SET
                        hourly_rate      = excluded.hourly_rate,
                        allowance        = excluded.allowance,
                        commission_rate  = excluded.commission_rate
                    """,
                    (brand_code, payroll_month, emp["nick_name"], emp["hourly_rate"], emp["allowance"], emp["commission_rate"]),
                )
            if emp_rows:
                imported_parts.append(f"員工資料（{len(emp_rows)} 人）")
        except Exception as exc:
            print(f"API 員工資料同步跳過: {exc}")

        # ── 2. 銷售資料 ─────────────────────────────────────────────
        try:
            sales_data = client.get_report("sale")
            sales_rows = transform_sales_report(sales_data, brand_code, payroll_month)
            cursor.execute(
                "DELETE FROM Sales WHERE brand_code = ? AND payroll_month = ?",
                (brand_code, payroll_month),
            )
            for s in sales_rows:
                cursor.execute(
                    "INSERT OR IGNORE INTO Products (brand_code, model, product_line) VALUES (?, ?, '未分類')",
                    (brand_code, s["model"]),
                )
                cursor.execute(
                    """
                    INSERT INTO Sales (brand_code, payroll_month, date, promoter_name, location, model, quantity, price)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (s["brand_code"], s["payroll_month"], s["date"], s["promoter_name"],
                     s["location"], s["model"], s["quantity"], s["price"]),
                )
            if sales_rows:
                imported_parts.append(f"銷售紀錄（{len(sales_rows)} 筆）")
        except Exception as exc:
            print(f"API 銷售資料同步跳過: {exc}")

        # ── 3. 出勤資料 ─────────────────────────────────────────────
        try:
            duty_data = client.get_report("duty")
            daily_rows, att_totals = transform_duty_report(duty_data, brand_code, payroll_month)
            cursor.execute(
                "DELETE FROM DailyAttendance WHERE brand_code = ? AND payroll_month = ?",
                (brand_code, payroll_month),
            )
            cursor.execute(
                "DELETE FROM Attendance WHERE brand_code = ? AND payroll_month = ?",
                (brand_code, payroll_month),
            )
            for d in daily_rows:
                cursor.execute(
                    """
                    INSERT INTO DailyAttendance (brand_code, payroll_month, work_date, nick_name, location,
                                                 normal_hours, actual_hours, ot_hours)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (d["brand_code"], d["payroll_month"], d["work_date"], d["nick_name"],
                     d["location"], d["normal_hours"], d["actual_hours"], d["ot_hours"]),
                )
            for (name, loc), totals in att_totals.items():
                cursor.execute(
                    """
                    INSERT INTO Attendance (brand_code, payroll_month, nick_name, location, days_worked, hours, ot_hours)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(brand_code, payroll_month, nick_name, location) DO UPDATE SET
                        days_worked = excluded.days_worked,
                        hours       = excluded.hours,
                        ot_hours    = excluded.ot_hours
                    """,
                    (brand_code, payroll_month, name, loc, totals["days"], totals["hours"], totals["ot"]),
                )
            if daily_rows:
                imported_parts.append(f"出勤紀錄（{len(daily_rows)} 日）")
        except Exception as exc:
            print(f"API 出勤資料同步跳過: {exc}")

        conn.commit()

        if not imported_parts:
            return True, "⚠️ API 同步完成，但未收到任何資料（可能遠端暫無 Toshiba 數據）。"
        return True, f"✅ 已從外部 API 同步 Toshiba 資料：{'、'.join(imported_parts)}。"

    except Exception as exc:
        conn.rollback()
        return False, f"❌ API 同步失敗: {str(exc)}"
    finally:
        conn.close()