import logging
import os

from flask import Flask, redirect, request, session, url_for

from app_config import ENABLE_HTTPS, HISTORY_FOLDER, LOG_FOLDER, SECRET_KEY, SSL_CERT_FILE, SSL_KEY_FILE, UPLOAD_FOLDER
from blueprints.attendance import bp as attendance_bp
from blueprints.main import bp as main_bp
from blueprints.sales import bp as sales_bp
from blueprints.settings import bp as settings_bp
from repository import ensure_core_tables
from services import seed_default_admin_user


def get_ssl_context():
    if not ENABLE_HTTPS:
        return None
    if SSL_CERT_FILE and SSL_KEY_FILE:
        return (SSL_CERT_FILE, SSL_KEY_FILE)
    return "adhoc"


def create_app():
    os.makedirs(HISTORY_FOLDER, exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(LOG_FOLDER, exist_ok=True)

    logging.basicConfig(
        filename=os.path.join(LOG_FOLDER, "system.log"),
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = ENABLE_HTTPS
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PREFERRED_URL_SCHEME"] = "https" if ENABLE_HTTPS else "http"

    ensure_core_tables()
    seed_default_admin_user()

    app.register_blueprint(main_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(settings_bp)

    @app.before_request
    def require_login():
        endpoint = request.endpoint or ""
        if endpoint == "static" or endpoint == "main.login":
            return None
        if endpoint == "main.logout":
            return None
        if not session.get("user"):
            return redirect(url_for("main.login", next=request.full_path))
        return None

    return app


app = create_app()


if __name__ == "__main__":
    ssl_context = get_ssl_context()
    scheme = "https" if ssl_context else "http"
    print(f" * Running on {scheme}://127.0.0.1:5001")
    app.run(host="0.0.0.0", port=5001, debug=True, ssl_context=ssl_context)
