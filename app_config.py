import os

SECRET_KEY = "super_secret_key"
DB_PATH = "payroll.db"
HISTORY_FOLDER = "history"
UPLOAD_FOLDER = "uploads"
LOG_FOLDER = "logs"
BACKUP_FOLDER = "backups"
DEFAULT_BRAND_CODE = os.environ.get("PAYROLL_DEFAULT_BRAND", "century_field").strip().lower() or "century_field"
SUPPORTED_BRANDS = {
	"century_field": "Century Field",
	"toshiba": "Toshiba",
}
ADMIN_USERS = {"admin", "auditor", "superuser"}
DEFAULT_ADMIN_USERNAME = os.environ.get("PAYROLL_ADMIN_USERNAME", "admin")
AUDIT_ADMIN_PASSWORD = os.environ.get("AUDIT_ADMIN_PASSWORD", "audit2026")
ENABLE_HTTPS = os.environ.get("PAYROLL_ENABLE_HTTPS", "0").lower() in {"1", "true", "yes", "on"}
SSL_CERT_FILE = os.environ.get("PAYROLL_SSL_CERT_FILE", "").strip()
SSL_KEY_FILE = os.environ.get("PAYROLL_SSL_KEY_FILE", "").strip()
TRUST_PROXY_HEADERS = os.environ.get("PAYROLL_TRUST_PROXY_HEADERS", "1").lower() in {"1", "true", "yes", "on"}
_secure_cookie_env = os.environ.get("PAYROLL_SESSION_COOKIE_SECURE", "").strip().lower()
if _secure_cookie_env:
	SESSION_COOKIE_SECURE = _secure_cookie_env in {"1", "true", "yes", "on"}
else:
	# Behind reverse proxy TLS termination (e.g. NPM), keep secure cookies enabled.
	SESSION_COOKIE_SECURE = ENABLE_HTTPS or TRUST_PROXY_HEADERS
MAX_LOGIN_ATTEMPTS = int(os.environ.get("PAYROLL_MAX_LOGIN_ATTEMPTS", "5"))
LOGIN_LOCK_MINUTES = int(os.environ.get("PAYROLL_LOGIN_LOCK_MINUTES", "15"))

# ── 外部 API 設定（Toshiba 品牌從遠端數據管理系統拉取銷售 / 出勤資料） ──
EXTERNAL_API_BASE_URL = os.environ.get("EXTERNAL_API_BASE_URL", "http://localhost:5000").rstrip("/")
EXTERNAL_API_KEY = os.environ.get("EXTERNAL_API_KEY", "")
