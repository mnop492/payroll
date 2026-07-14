import os

SECRET_KEY = "super_secret_key"
DB_PATH = "payroll.db"
HISTORY_FOLDER = "history"
UPLOAD_FOLDER = "uploads"
LOG_FOLDER = "logs"
BACKUP_FOLDER = "backups"
ADMIN_USERS = {"admin", "auditor", "superuser"}
DEFAULT_ADMIN_USERNAME = os.environ.get("PAYROLL_ADMIN_USERNAME", "admin")
AUDIT_ADMIN_PASSWORD = os.environ.get("AUDIT_ADMIN_PASSWORD", "audit2026")
ENABLE_HTTPS = os.environ.get("PAYROLL_ENABLE_HTTPS", "0").lower() in {"1", "true", "yes", "on"}
SSL_CERT_FILE = os.environ.get("PAYROLL_SSL_CERT_FILE", "").strip()
SSL_KEY_FILE = os.environ.get("PAYROLL_SSL_KEY_FILE", "").strip()
MAX_LOGIN_ATTEMPTS = int(os.environ.get("PAYROLL_MAX_LOGIN_ATTEMPTS", "5"))
LOGIN_LOCK_MINUTES = int(os.environ.get("PAYROLL_LOGIN_LOCK_MINUTES", "15"))
