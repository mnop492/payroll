import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

# 配置檔路徑（與專案根目錄相同）
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "external_api_config.json")


def _load_config():
    """從 external_api_config.json 載入設定，環境變數優先覆蓋。"""
    defaults = {"base_url": "http://localhost:5000", "api_key": ""}
    from app_config import EXTERNAL_API_BASE_URL, EXTERNAL_API_KEY

    # 環境變數優先
    if EXTERNAL_API_BASE_URL:
        defaults["base_url"] = EXTERNAL_API_BASE_URL
    if EXTERNAL_API_KEY:
        defaults["api_key"] = EXTERNAL_API_KEY
    else:
        # 嘗試從 JSON 檔讀取
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
                defaults.setdefault("base_url", saved.get("base_url", defaults["base_url"]))
                defaults.setdefault("api_key", saved.get("api_key", defaults["api_key"]))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    return defaults


class ExternalAPIClient:
    """連接外部數據管理系統（API_SUMMARY.md 描述的 port 5000 API）的 HTTP 客戶端。
    
    用於 Toshiba 品牌從遠端系統拉取銷售與出勤記錄，
    取代 Excel 匯入流程。
    """

    def __init__(self, base_url=None, api_key=None):
        config = _load_config()
        self.base_url = (base_url or config["base_url"]).rstrip("/")
        self.api_key = api_key or config["api_key"]
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        })

    # ── 讀取報表 ──────────────────────────────────────────────────────

    def get_report(self, report_type):
        """讀取本機報表 Excel（回傳 JSON 陣列）。

        Args:
            report_type: sale | profile | product | duty | insert | cancel | push
        """
        url = f"{self.base_url}/api/v1/report/{report_type}"
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            logger.error("API get_report(%s) 失敗: %s", report_type, exc)
            raise

    # ── 寫入待處理項目 ────────────────────────────────────────────────

    def post_add_to_action(self, action_type, data):
        """新增待處理項目至 Excel。

        Args:
            action_type: insert | cancel | push
            data: list of dicts
        """
        url = f"{self.base_url}/api/v1/add_to_action/{action_type}"
        try:
            resp = self.session.post(url, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            logger.error("API add_to_action(%s) 失敗: %s", action_type, exc)
            raise

    # ── 執行操作（寫入遠端 API） ──────────────────────────────────────

    def post_execute_action(self, action_type, mode="all", data=None):
        """執行待處理項目，真正寫入遠端系統。

        Args:
            action_type: insert | cancel | push
            mode: "all" 或 "selected"
            data: 當 mode="selected" 時要傳入的資料清單
        """
        url = f"{self.base_url}/api/v1/execute_action/{action_type}"
        body = {"mode": mode}
        if data:
            body["data"] = data
        try:
            resp = self.session.post(url, json=body, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            logger.error("API execute_action(%s) 失敗: %s", action_type, exc)
            raise
