import os
import sqlite3

from app_config import DB_PATH, DEFAULT_BRAND_CODE, HISTORY_FOLDER, SUPPORTED_BRANDS


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
            brand_code TEXT NOT NULL DEFAULT 'century_field',
            payroll_month TEXT NOT NULL,
            nick_name TEXT NOT NULL,
            hourly_rate REAL,
            allowance REAL,
            commission_rate REAL,
            UNIQUE(brand_code, payroll_month, nick_name),
            FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
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


def ensure_user_brand_permissions_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS UserBrandPermissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            brand_code TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(username, brand_code),
            FOREIGN KEY (username) REFERENCES Users(username),
            FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_initial_user_brand_permissions():
    conn = get_db_connection()
    existing = conn.execute("SELECT COUNT(*) AS c FROM UserBrandPermissions").fetchone()
    if existing and int(existing["c"] or 0) == 0:
        conn.execute(
            """
            INSERT INTO UserBrandPermissions (username, brand_code)
            SELECT u.username, b.brand_code
            FROM Users u
            JOIN Brands b ON b.is_active = 1
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


def ensure_brands_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS Brands (
            brand_code TEXT PRIMARY KEY,
            brand_name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for code, name in SUPPORTED_BRANDS.items():
        conn.execute(
            """
            INSERT INTO Brands (brand_code, brand_name, is_active)
            VALUES (?, ?, 1)
            ON CONFLICT(brand_code) DO UPDATE SET
                brand_name = excluded.brand_name,
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (code, name),
        )
    conn.commit()
    conn.close()


def ensure_brand_month_input_source_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS BrandMonthInputSource (
            brand_code TEXT NOT NULL,
            payroll_month TEXT NOT NULL,
            input_source TEXT NOT NULL CHECK (input_source IN ('excel', 'web')),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (brand_code, payroll_month),
            FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_auto_backup_settings_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS AutoBackupSettings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER NOT NULL DEFAULT 0,
            backup_time TEXT NOT NULL DEFAULT '02:00',
            last_run_date TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO AutoBackupSettings (id, enabled, backup_time, last_run_date)
        VALUES (1, 0, '02:00', NULL)
        """
    )
    conn.commit()
    conn.close()


def _has_column(conn, table_name, column_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def ensure_brand_columns_for_core_tables():
    conn = get_db_connection()

    # DailyAttendance / Sales can be evolved with add-column migration.
    for table_name in ("DailyAttendance", "Sales"):
        if not _table_exists(conn, table_name):
            continue
        if _has_column(conn, table_name, "brand_code"):
            continue
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN brand_code TEXT NOT NULL DEFAULT '{DEFAULT_BRAND_CODE}'"
        )

    # MonthlyRates requires unique key upgrade to include brand_code.
    if _table_exists(conn, "MonthlyRates") and not _has_column(conn, "MonthlyRates", "brand_code"):
        conn.execute("ALTER TABLE MonthlyRates RENAME TO MonthlyRates_legacy")
        conn.execute(
            """
            CREATE TABLE MonthlyRates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_code TEXT NOT NULL DEFAULT 'century_field',
                payroll_month TEXT NOT NULL,
                nick_name TEXT NOT NULL,
                hourly_rate REAL,
                allowance REAL,
                commission_rate REAL,
                UNIQUE(brand_code, payroll_month, nick_name),
                FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO MonthlyRates (id, brand_code, payroll_month, nick_name, hourly_rate, allowance, commission_rate)
            SELECT id, ?, payroll_month, nick_name, hourly_rate, allowance, commission_rate
            FROM MonthlyRates_legacy
            """,
            (DEFAULT_BRAND_CODE,),
        )
        conn.execute("DROP TABLE MonthlyRates_legacy")

    # Attendance requires unique key upgrade to include brand_code.
    if _table_exists(conn, "Attendance") and not _has_column(conn, "Attendance", "brand_code"):
        conn.execute("ALTER TABLE Attendance RENAME TO Attendance_legacy")
        conn.execute(
            """
            CREATE TABLE Attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_code TEXT NOT NULL DEFAULT 'century_field',
                payroll_month TEXT,
                nick_name TEXT,
                location TEXT,
                days_worked INTEGER DEFAULT 0,
                hours REAL DEFAULT 0,
                ot_hours REAL DEFAULT 0,
                expenses REAL DEFAULT 0,
                adjustment REAL DEFAULT 0,
                attendance_bonus REAL DEFAULT 0,
                basic_pay_override REAL,
                allowance_override REAL,
                UNIQUE(brand_code, payroll_month, nick_name, location),
                FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO Attendance (
                id, brand_code, payroll_month, nick_name, location,
                days_worked, hours, ot_hours, expenses, adjustment,
                attendance_bonus, basic_pay_override, allowance_override
            )
            SELECT
                id, ?, payroll_month, nick_name, location,
                days_worked, hours, ot_hours, expenses, adjustment,
                attendance_bonus, basic_pay_override, allowance_override
            FROM Attendance_legacy
            """,
            (DEFAULT_BRAND_CODE,),
        )
        conn.execute("DROP TABLE Attendance_legacy")

    # Employees should be isolated by brand and allow same nick_name across brands.
    if _table_exists(conn, "Employees") and not _has_column(conn, "Employees", "brand_code"):
        conn.execute("ALTER TABLE Employees RENAME TO Employees_legacy")
        conn.execute(
            """
            CREATE TABLE Employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_code TEXT NOT NULL DEFAULT 'century_field',
                nick_name TEXT NOT NULL,
                hourly_rate REAL DEFAULT 0,
                allowance REAL DEFAULT 0,
                commission_rate REAL DEFAULT 0.03,
                require_mpf INTEGER DEFAULT 0,
                mpf_start_month TEXT,
                full_name TEXT,
                UNIQUE(brand_code, nick_name),
                FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO Employees (
                id, brand_code, nick_name, hourly_rate, allowance, commission_rate,
                require_mpf, mpf_start_month, full_name
            )
            SELECT
                id, ?, nick_name, hourly_rate, allowance, commission_rate,
                require_mpf, mpf_start_month, full_name
            FROM Employees_legacy
            """,
            (DEFAULT_BRAND_CODE,),
        )
        conn.execute("DROP TABLE Employees_legacy")

    # Locations should be isolated by brand and allow same location names across brands.
    if _table_exists(conn, "Locations") and not _has_column(conn, "Locations", "brand_code"):
        conn.execute("ALTER TABLE Locations RENAME TO Locations_legacy")
        conn.execute(
            """
            CREATE TABLE Locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_code TEXT NOT NULL DEFAULT 'century_field',
                name TEXT NOT NULL,
                display_name TEXT,
                region TEXT,
                UNIQUE(brand_code, name),
                FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO Locations (id, brand_code, name, display_name, region)
            SELECT id, ?, name, display_name, region
            FROM Locations_legacy
            """,
            (DEFAULT_BRAND_CODE,),
        )
        conn.execute("DROP TABLE Locations_legacy")

    # Products should be isolated by brand and allow same model names across brands.
    if _table_exists(conn, "Products") and not _has_column(conn, "Products", "brand_code"):
        conn.execute("ALTER TABLE Products RENAME TO Products_legacy")
        conn.execute(
            """
            CREATE TABLE Products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_code TEXT NOT NULL DEFAULT 'century_field',
                model TEXT NOT NULL,
                product_line TEXT,
                commission_rate REAL DEFAULT 0.03,
                UNIQUE(brand_code, model),
                FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO Products (id, brand_code, model, product_line, commission_rate)
            SELECT id, ?, model, product_line, commission_rate
            FROM Products_legacy
            """,
            (DEFAULT_BRAND_CODE,),
        )
        conn.execute("DROP TABLE Products_legacy")

    # Special commissions should be isolated by brand.
    if _table_exists(conn, "SpecialCommissions") and not _has_column(conn, "SpecialCommissions", "brand_code"):
        conn.execute("ALTER TABLE SpecialCommissions RENAME TO SpecialCommissions_legacy")
        conn.execute(
            """
            CREATE TABLE SpecialCommissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_code TEXT NOT NULL DEFAULT 'century_field',
                model TEXT NOT NULL,
                start_month TEXT NOT NULL,
                end_month TEXT NOT NULL,
                rate REAL NOT NULL,
                FOREIGN KEY (brand_code) REFERENCES Brands(brand_code)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO SpecialCommissions (id, brand_code, model, start_month, end_month, rate)
            SELECT id, ?, model, start_month, end_month, rate
            FROM SpecialCommissions_legacy
            """,
            (DEFAULT_BRAND_CODE,),
        )
        conn.execute("DROP TABLE SpecialCommissions_legacy")

    conn.commit()
    conn.close()


def ensure_dailyattendance_sync_triggers():
    conn = get_db_connection()
    if not _table_exists(conn, "DailyAttendance") or not _table_exists(conn, "Attendance"):
        conn.close()
        return

    # Drop legacy trigger bodies that may still reference renamed tables.
    for trigger_name in (
        "update_attendance_after_insert",
        "update_attendance_after_delete",
        "update_attendance_after_update",
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")

    conn.execute(
        """
        CREATE TRIGGER update_attendance_after_insert
        AFTER INSERT ON DailyAttendance
        FOR EACH ROW
        BEGIN
            INSERT OR IGNORE INTO Attendance (brand_code, payroll_month, nick_name, location, days_worked, hours, ot_hours, expenses, adjustment, attendance_bonus)
            VALUES (NEW.brand_code, NEW.payroll_month, NEW.nick_name, NEW.location, 0, 0, 0, 0, 0, 0);

            UPDATE Attendance
            SET
                days_worked = (
                    SELECT COUNT(*)
                    FROM DailyAttendance
                    WHERE brand_code = NEW.brand_code
                      AND payroll_month = NEW.payroll_month
                      AND nick_name = NEW.nick_name
                      AND location = NEW.location
                ),
                hours = COALESCE((
                    SELECT SUM(actual_hours - ot_hours)
                    FROM DailyAttendance
                    WHERE brand_code = NEW.brand_code
                      AND payroll_month = NEW.payroll_month
                      AND nick_name = NEW.nick_name
                      AND location = NEW.location
                ), 0),
                ot_hours = COALESCE((
                    SELECT SUM(ot_hours)
                    FROM DailyAttendance
                    WHERE brand_code = NEW.brand_code
                      AND payroll_month = NEW.payroll_month
                      AND nick_name = NEW.nick_name
                      AND location = NEW.location
                ), 0)
            WHERE brand_code = NEW.brand_code
              AND payroll_month = NEW.payroll_month
              AND nick_name = NEW.nick_name
              AND location = NEW.location;
        END
        """
    )

    conn.execute(
        """
        CREATE TRIGGER update_attendance_after_delete
        AFTER DELETE ON DailyAttendance
        FOR EACH ROW
        BEGIN
            UPDATE Attendance
            SET
                days_worked = (
                    SELECT COUNT(*)
                    FROM DailyAttendance
                    WHERE brand_code = OLD.brand_code
                      AND payroll_month = OLD.payroll_month
                      AND nick_name = OLD.nick_name
                      AND location = OLD.location
                ),
                hours = COALESCE((
                    SELECT SUM(actual_hours - ot_hours)
                    FROM DailyAttendance
                    WHERE brand_code = OLD.brand_code
                      AND payroll_month = OLD.payroll_month
                      AND nick_name = OLD.nick_name
                      AND location = OLD.location
                ), 0),
                ot_hours = COALESCE((
                    SELECT SUM(ot_hours)
                    FROM DailyAttendance
                    WHERE brand_code = OLD.brand_code
                      AND payroll_month = OLD.payroll_month
                      AND nick_name = OLD.nick_name
                      AND location = OLD.location
                ), 0)
            WHERE brand_code = OLD.brand_code
              AND payroll_month = OLD.payroll_month
              AND nick_name = OLD.nick_name
              AND location = OLD.location;
        END
        """
    )

    conn.execute(
        """
        CREATE TRIGGER update_attendance_after_update
        AFTER UPDATE ON DailyAttendance
        FOR EACH ROW
        BEGIN
            UPDATE Attendance
            SET
                days_worked = (
                    SELECT COUNT(*)
                    FROM DailyAttendance
                    WHERE brand_code = NEW.brand_code
                      AND payroll_month = NEW.payroll_month
                      AND nick_name = NEW.nick_name
                      AND location = NEW.location
                ),
                hours = COALESCE((
                    SELECT SUM(actual_hours - ot_hours)
                    FROM DailyAttendance
                    WHERE brand_code = NEW.brand_code
                      AND payroll_month = NEW.payroll_month
                      AND nick_name = NEW.nick_name
                      AND location = NEW.location
                ), 0),
                ot_hours = COALESCE((
                    SELECT SUM(ot_hours)
                    FROM DailyAttendance
                    WHERE brand_code = NEW.brand_code
                      AND payroll_month = NEW.payroll_month
                      AND nick_name = NEW.nick_name
                      AND location = NEW.location
                ), 0)
            WHERE brand_code = NEW.brand_code
              AND payroll_month = NEW.payroll_month
              AND nick_name = NEW.nick_name
              AND location = NEW.location;
        END
        """
    )

    conn.commit()
    conn.close()


def ensure_core_tables():
    ensure_brands_table()
    ensure_audit_table()
    ensure_monthly_rates_table()
    ensure_users_table()
    ensure_login_attempts_table()
    ensure_user_brand_permissions_table()
    ensure_initial_user_brand_permissions()
    ensure_month_input_source_table()
    ensure_brand_month_input_source_table()
    ensure_auto_backup_settings_table()
    ensure_brand_columns_for_core_tables()
    ensure_dailyattendance_sync_triggers()


def get_auto_backup_settings():
    conn = get_db_connection()
    row = conn.execute(
        "SELECT enabled, backup_time, last_run_date, updated_at FROM AutoBackupSettings WHERE id = 1"
    ).fetchone()
    conn.close()
    if not row:
        return {
            "enabled": 0,
            "backup_time": "02:00",
            "last_run_date": None,
            "updated_at": None,
        }
    return dict(row)


def set_auto_backup_settings(enabled, backup_time):
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE AutoBackupSettings
        SET enabled = ?, backup_time = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (1 if enabled else 0, backup_time),
    )
    conn.commit()
    conn.close()


def mark_auto_backup_run(run_date):
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE AutoBackupSettings
        SET last_run_date = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (run_date,),
    )
    conn.commit()
    conn.close()


def try_claim_auto_backup_run(run_date, current_hhmm):
        conn = get_db_connection()
        cur = conn.execute(
                """
                UPDATE AutoBackupSettings
                SET last_run_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                    AND enabled = 1
                    AND backup_time <= ?
                    AND (last_run_date IS NULL OR last_run_date <> ?)
                """,
                (run_date, current_hhmm, run_date),
        )
        conn.commit()
        claimed = cur.rowcount > 0
        conn.close()
        return claimed


def set_month_input_source(payroll_month, input_source, brand_code=DEFAULT_BRAND_CODE):
    if not payroll_month or input_source not in {"excel", "web"}:
        return

    brand_code = (brand_code or DEFAULT_BRAND_CODE).strip().lower()
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO BrandMonthInputSource (brand_code, payroll_month, input_source)
        VALUES (?, ?, ?)
        ON CONFLICT(brand_code, payroll_month) DO UPDATE SET
            input_source = excluded.input_source,
            updated_at = CURRENT_TIMESTAMP
        """,
        (brand_code, payroll_month, input_source),
    )

    # Backward compatibility for legacy single-brand reads.
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


def get_month_input_source(payroll_month, brand_code=DEFAULT_BRAND_CODE):
    if not payroll_month:
        return None

    brand_code = (brand_code or DEFAULT_BRAND_CODE).strip().lower()
    conn = get_db_connection()
    row = conn.execute(
        "SELECT input_source FROM BrandMonthInputSource WHERE brand_code = ? AND payroll_month = ?",
        (brand_code, payroll_month),
    ).fetchone()
    if row:
        conn.close()
        return row["input_source"]

    row = conn.execute(
        "SELECT input_source FROM MonthInputSource WHERE payroll_month = ?",
        (payroll_month,),
    ).fetchone()
    conn.close()
    return row["input_source"] if row else None


def get_available_brands():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT brand_code, brand_name FROM Brands WHERE is_active = 1 ORDER BY brand_name"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_user_allowed_brands(username):
    if not username:
        return []
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT b.brand_code, b.brand_name
        FROM UserBrandPermissions p
        JOIN Brands b ON b.brand_code = p.brand_code
        WHERE p.username = ? AND b.is_active = 1
        ORDER BY b.brand_name
        """,
        (username,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_user_allowed_brand_codes(username):
    return {row["brand_code"] for row in get_user_allowed_brands(username)}


def grant_all_active_brands_to_user(username):
    if not username:
        return
    conn = get_db_connection()
    conn.execute(
        """
        INSERT OR IGNORE INTO UserBrandPermissions (username, brand_code)
        SELECT ?, brand_code FROM Brands WHERE is_active = 1
        """,
        (username,),
    )
    conn.commit()
    conn.close()


def set_user_brand_permissions(username, brand_codes):
    if not username:
        return
    codes = sorted({(code or "").strip().lower() for code in (brand_codes or []) if code})
    conn = get_db_connection()
    conn.execute("DELETE FROM UserBrandPermissions WHERE username = ?", (username,))
    if codes:
        valid_rows = conn.execute(
            f"SELECT brand_code FROM Brands WHERE is_active = 1 AND brand_code IN ({','.join('?' * len(codes))})",
            codes,
        ).fetchall()
        valid_codes = [row["brand_code"] for row in valid_rows]
        for code in valid_codes:
            conn.execute(
                "INSERT OR IGNORE INTO UserBrandPermissions (username, brand_code) VALUES (?, ?)",
                (username, code),
            )
    conn.commit()
    conn.close()


def get_user_brand_permissions_map():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT username, brand_code FROM UserBrandPermissions ORDER BY username, brand_code"
    ).fetchall()
    conn.close()
    mapping = {}
    for row in rows:
        mapping.setdefault(row["username"], []).append(row["brand_code"])
    return mapping


def get_all_brands():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT brand_code, brand_name, is_active, created_at, updated_at FROM Brands ORDER BY brand_name"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_brand_name(brand_code):
    if not brand_code:
        return brand_code
    conn = get_db_connection()
    row = conn.execute(
        "SELECT brand_name FROM Brands WHERE brand_code = ?",
        ((brand_code or DEFAULT_BRAND_CODE).strip().lower(),),
    ).fetchone()
    conn.close()
    return row["brand_name"] if row else brand_code


def is_valid_brand_code(brand_code, active_only=True):
    candidate = (brand_code or "").strip().lower()
    if not candidate:
        return False
    conn = get_db_connection()
    if active_only:
        row = conn.execute(
            "SELECT 1 FROM Brands WHERE brand_code = ? AND is_active = 1",
            (candidate,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM Brands WHERE brand_code = ?",
            (candidate,),
        ).fetchone()
    conn.close()
    return bool(row)


def month_has_excel_history(payroll_month, brand_code=DEFAULT_BRAND_CODE):
    if not payroll_month:
        return False
    if not os.path.isdir(HISTORY_FOLDER):
        return False

    month_key = payroll_month.replace("-", "")
    brand_name = str(get_brand_name(brand_code) or "").lower()
    for filename in os.listdir(HISTORY_FOLDER):
        if not filename.endswith(".xlsx") or filename.startswith("~"):
            continue
        if filename.startswith(month_key):
            if brand_name and brand_name not in filename.lower() and brand_code != DEFAULT_BRAND_CODE:
                continue
            return True
    return False


def sync_attendance_summary(month, nick_name, location, brand_code=DEFAULT_BRAND_CODE):
    conn = get_db_connection()
    summary = conn.execute(
        """
        SELECT
            COUNT(work_date) AS t_days,
            SUM(actual_hours - ot_hours) AS t_hours,
            SUM(ot_hours) AS t_ot
        FROM DailyAttendance
        WHERE brand_code = ? AND payroll_month = ? AND nick_name = ? AND location = ?
        """,
        (brand_code, month, nick_name, location),
    ).fetchone()

    days = summary["t_days"] or 0
    hours = summary["t_hours"] or 0.0
    ot = summary["t_ot"] or 0.0

    conn.execute(
        """
        INSERT OR IGNORE INTO Attendance (brand_code, payroll_month, nick_name, location, days_worked, hours, ot_hours)
        VALUES (?, ?, ?, ?, 0, 0, 0)
        """,
        (brand_code, month, nick_name, location),
    )
    conn.execute(
        """
        UPDATE Attendance
        SET days_worked = ?, hours = ?, ot_hours = ?
        WHERE brand_code = ? AND payroll_month = ? AND nick_name = ? AND location = ?
        """,
        (days, hours, ot, brand_code, month, nick_name, location),
    )
    conn.commit()
    conn.close()


def fetch_index_context(current_month, payroll_results, brand_code=DEFAULT_BRAND_CODE):
    conn = get_db_connection()
    records = conn.execute(
        "SELECT * FROM Sales WHERE brand_code = ? AND payroll_month = ?",
        (brand_code, current_month),
    ).fetchall()
    attendances_raw = conn.execute(
        "SELECT * FROM Attendance WHERE brand_code = ? AND payroll_month = ?",
        (brand_code, current_month),
    ).fetchall()
    staff_summary_raw = conn.execute(
        """
        SELECT promoter_name AS name, location AS main_location,
               COUNT(*) AS total_entries, SUM(quantity * price) AS total_amount
        FROM Sales WHERE brand_code = ? AND payroll_month = ?
        GROUP BY promoter_name, location ORDER BY name, total_amount DESC
        """,
        (brand_code, current_month),
    ).fetchall()
    locations = conn.execute(
        "SELECT name FROM Locations WHERE brand_code = ? ORDER BY name",
        (brand_code,),
    ).fetchall()
    products = conn.execute(
        "SELECT model FROM Products WHERE brand_code = ? ORDER BY model",
        (brand_code,),
    ).fetchall()
    employees_rows = conn.execute(
        "SELECT nick_name, full_name, hourly_rate, commission_rate FROM Employees WHERE brand_code = ? ORDER BY nick_name",
        (brand_code,),
    ).fetchall()
    monthly_rates_rows = conn.execute(
        "SELECT nick_name, hourly_rate, commission_rate FROM MonthlyRates WHERE brand_code = ? AND payroll_month = ?",
        (brand_code, current_month),
    ).fetchall()
    conn.close()

    month_input_source = get_month_input_source(current_month, brand_code=brand_code)
    has_excel_history = month_has_excel_history(current_month, brand_code=brand_code)

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


def fetch_settings_context(current_month, brand_code=DEFAULT_BRAND_CODE):
    conn = get_db_connection()
    employees = conn.execute(
        "SELECT * FROM Employees WHERE brand_code = ? ORDER BY nick_name",
        (brand_code,),
    ).fetchall()
    monthly_rates = conn.execute(
        "SELECT nick_name, hourly_rate, commission_rate FROM MonthlyRates WHERE brand_code = ? AND payroll_month = ?",
        (brand_code, current_month),
    ).fetchall()
    conn.close()
    monthly_map = {row["nick_name"]: row["hourly_rate"] for row in monthly_rates}
    monthly_comm_map = {row["nick_name"]: row["commission_rate"] for row in monthly_rates}
    return employees, monthly_map, monthly_comm_map


def fetch_manage_products_context(brand_code=DEFAULT_BRAND_CODE):
    conn = get_db_connection()
    products = conn.execute(
        "SELECT * FROM Products WHERE brand_code = ? ORDER BY model",
        (brand_code,),
    ).fetchall()
    special_rules = conn.execute(
        "SELECT * FROM SpecialCommissions WHERE brand_code = ? ORDER BY start_month DESC",
        (brand_code,),
    ).fetchall()
    conn.close()
    return products, special_rules


def fetch_manage_locations_context(brand_code=DEFAULT_BRAND_CODE):
    conn = get_db_connection()
    locations = conn.execute(
        "SELECT * FROM Locations WHERE brand_code = ? ORDER BY region, name",
        (brand_code,),
    ).fetchall()
    conn.close()
    return locations


def fetch_daily_attendance(month, nick_name, location, brand_code=DEFAULT_BRAND_CODE):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, work_date, in_time, out_time, normal_hours, actual_hours, ot_hours, location
        FROM DailyAttendance
        WHERE brand_code = ? AND payroll_month = ? AND nick_name = ? AND location = ?
        ORDER BY work_date
        """,
        (brand_code, month, nick_name, location),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_sales_records(month, nick_name, location, brand_code=DEFAULT_BRAND_CODE):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, date, location, model, quantity, price
        FROM Sales
        WHERE brand_code = ? AND payroll_month = ? AND promoter_name = ? AND location = ?
        ORDER BY date
        """,
        (brand_code, month, nick_name, location),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
