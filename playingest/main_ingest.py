"""PlayIngest — cliente de ingest remoto para o PlayLine."""

import json
import logging
import os
import sys
import threading
from pathlib import Path

import requests
import webview

_LOG_PATH = (
    Path(sys.executable).parent / "PlayIngest.log"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "PlayIngest.log"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("playingest")

_UI_DIR = (
    Path(sys._MEIPASS) / "ui"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "ui"
)

_CONFIG_FILE = (
    Path(sys.executable).parent / "ingest_config.json"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "ingest_config.json"
)

_SUPPORTED_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".ts", ".mxf", ".mpg", ".mpeg", ".wmv", ".flv", ".webm"}


def _load_config() -> dict:
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_config(data: dict) -> None:
    try:
        cfg = _load_config()
        cfg.update(data)
        _CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")
    except Exception:
        pass


class IngestAPI:
    """API exposta ao JavaScript via pywebview."""

    def __init__(self):
        self._token: str | None = None
        self._base_url: str | None = None

    # ── Persistência ────────────────────────────────────────────────────

    def get_last_ip(self) -> str:
        return _load_config().get("last_ip", "")

    # ── Conectividade ────────────────────────────────────────────────────

    def ping(self, ip: str) -> dict:
        url = f"http://{ip}:18000/api/ping"
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200 and r.json().get("playline"):
                _save_config({"last_ip": ip})
                self._base_url = f"http://{ip}:18000"
                logger.info("Conectado ao servidor %s", ip)
                return {"ok": True}
        except Exception as exc:
            logger.warning("Falha ao conectar em %s: %s", ip, exc)
        self._base_url = None
        return {"ok": False}

    # ── Autenticação ─────────────────────────────────────────────────────

    def login(self, username: str, password: str) -> dict:
        if not self._base_url:
            return {"ok": False, "error": "Sem conexão com o servidor"}
        try:
            r = requests.post(
                f"{self._base_url}/api/login",
                json={"username": username, "password": password},
                timeout=6,
            )
            data = r.json()
            if r.status_code == 200 and data.get("ok"):
                self._token = data["token"]
                logger.info("Login bem-sucedido (usuário: %s)", username)
                return {"ok": True}
            err = data.get("error", "Credenciais inválidas")
            logger.warning("Falha no login: %s", err)
            return {"ok": False, "error": err}
        except Exception as exc:
            logger.error("Erro ao autenticar: %s", exc)
            return {"ok": False, "error": str(exc)}

    # ── Biblioteca ───────────────────────────────────────────────────────

    def get_subfolders(self) -> dict:
        if not self._base_url or not self._token:
            return {"ok": False, "subfolders": []}
        try:
            r = requests.get(
                f"{self._base_url}/api/library",
                cookies={"playline_session": self._token},
                timeout=6,
            )
            data = r.json()
            return {"ok": True, "subfolders": data.get("subfolders", [])}
        except Exception as exc:
            return {"ok": False, "subfolders": [], "error": str(exc)}

    # ── Informações do servidor (para upload direto via XHR no JS) ───────

    def get_server_info(self) -> dict:
        return {
            "base_url": self._base_url or "",
            "token": self._token or "",
        }


def main():
    api = IngestAPI()
    window = webview.create_window(
        "PlayIngest",
        url=str(_UI_DIR / "index.html"),
        js_api=api,
        width=720,
        height=600,
        resizable=True,
        min_size=(640, 520),
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
