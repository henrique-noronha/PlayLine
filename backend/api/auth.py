"""Autenticação e gerenciamento de sessões do PlayLine."""

import asyncio
import base64
import json
import logging
import secrets
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core import settings as app_settings

logger = logging.getLogger(__name__)

router = APIRouter()

if getattr(sys, 'frozen', False):
    _DATA_DIR = Path(sys.executable).parent
else:
    _DATA_DIR = Path(__file__).parent.parent

SESSION_TTL = 8 * 3600

_SESSIONS_FILE = _DATA_DIR / "sessions.json"


def _load_sessions() -> dict[str, float]:
    try:
        if not _SESSIONS_FILE.exists():
            return {}
        data = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
        now = time.time()
        return {t: exp for t, exp in data.items() if isinstance(exp, (int, float)) and exp > now}
    except Exception:
        return {}


def save_sessions(sessions: dict[str, float]) -> None:
    now = time.time()
    expired = [t for t, exp in sessions.items() if exp <= now]
    for t in expired:
        sessions.pop(t, None)
    try:
        _SESSIONS_FILE.write_text(json.dumps(sessions), encoding="utf-8")
    except Exception as exc:
        logger.warning("Não foi possível salvar sessões: %s", exc)


SESSIONS: dict[str, float] = _load_sessions()


def session_valid(token: str) -> bool:
    """Único critério de sessão válida, compartilhado pelo middleware HTTP e pelos WebSockets."""
    return bool(token) and SESSIONS.get(token, 0) > time.time()


def request_token(request: Request) -> str:
    return request.cookies.get("playline_session") or request.query_params.get("session_token") or ""


# ── Brute-force throttle ──────────────────────────────────────────────────

_LOGIN_MAX_FAILS   = 5
_LOGIN_WINDOW_SEC  = 300
_LOGIN_LOCKOUT_SEC = 60
_login_fails: dict[str, list[float]] = {}


def _login_blocked(ip: str) -> bool:
    now = time.time()
    attempts = _login_fails.get(ip)
    if not attempts:
        return False
    attempts[:] = [t for t in attempts if now - t < _LOGIN_WINDOW_SEC]
    if not attempts:
        _login_fails.pop(ip, None)
        return False
    if len(attempts) >= _LOGIN_MAX_FAILS:
        last = attempts[-1]
        lockout = _LOGIN_LOCKOUT_SEC * (2 ** (len(attempts) - _LOGIN_MAX_FAILS))
        if now - last < lockout:
            return True
    return False


def _login_record_fail(ip: str):
    _login_fails.setdefault(ip, []).append(time.time())


def _login_clear(ip: str):
    _login_fails.pop(ip, None)


# ── Login HTML ────────────────────────────────────────────────────────────

def _brand_logo_file() -> Optional[Path]:
    if getattr(sys, "frozen", False):
        logos_dir = Path(sys.executable).parent / "logos"
    else:
        logos_dir = Path(__file__).parent.parent / "logos"
    for name in ("LogoPlayLineD.png", "FavPlayline.png"):
        lp = logos_dir / name
        if lp.exists():
            return lp
    return None


def _build_login_html(error: bool = False) -> str:
    logo_tag = "<span style='font-size:26px;font-weight:700;color:#e5e7eb'>PlayLine</span>"
    lp = _brand_logo_file()
    if lp:
        b64 = base64.b64encode(lp.read_bytes()).decode()
        logo_tag = f'<img src="data:image/png;base64,{b64}" style="max-width:280px;max-height:140px;object-fit:contain" alt="PlayLine" />'
    server_lang = app_settings.get_language()

    error_html = """<p data-l="err" style="color:#ef4444;font-size:12px;text-align:center;margin-top:4px">
        Usuário ou senha incorretos.</p>""" if error else ""

    return f"""<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlayLine — Autenticação</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#111827;display:flex;flex-direction:column;align-items:center;
  justify-content:center;height:100vh;gap:32px;
  font-family:'Segoe UI',system-ui,sans-serif;color:#e5e7eb}}
.logo-wrap{{display:flex;flex-direction:column;align-items:center;gap:12px}}
.subtitle{{font-size:12px;color:#6b7280;letter-spacing:.08em;text-transform:uppercase;font-weight:500}}
form{{display:flex;flex-direction:column;gap:12px;width:280px}}
.field{{display:flex;flex-direction:column;gap:5px}}
label{{font-size:11px;color:#4b5563;font-weight:600;letter-spacing:.06em;text-transform:uppercase}}
input{{background:#1a2332;border:1px solid #2d3748;border-radius:8px;color:#e5e7eb;
  font-size:14px;padding:10px 13px;outline:none;transition:border-color .15s;width:100%;
  font-family:'Segoe UI',system-ui,sans-serif}}
input:focus{{border-color:#4f8ef7;background:#1e2a40}}
button{{background:#4f8ef7;border:none;border-radius:8px;color:#fff;cursor:pointer;
  font-size:13px;font-weight:600;padding:11px;width:100%;margin-top:4px;
  transition:background .15s;letter-spacing:.02em}}
button:hover{{background:#3b7de8}}
</style></head><body>
<div class="logo-wrap">
  {logo_tag}
  <span class="subtitle" data-l="sub">Autenticação</span>
</div>
{error_html}
<form method="post" action="/login">
  <div class="field"><label data-l="user">Usuário</label>
    <input type="text" name="username" autocomplete="username" autofocus /></div>
  <div class="field"><label data-l="pass">Senha</label>
    <input type="password" name="password" autocomplete="current-password" /></div>
  <button type="submit" data-l="go">Entrar</button>
</form>
<script>
(function () {{
  var L = {{
    pt: {{ title: "PlayLine — Autenticação", sub: "Autenticação", user: "Usuário", pass: "Senha", go: "Entrar", err: "Usuário ou senha incorretos." }},
    en: {{ title: "PlayLine · Sign in", sub: "Sign in", user: "Username", pass: "Password", go: "Sign in", err: "Incorrect username or password." }},
    es: {{ title: "PlayLine · Iniciar sesión", sub: "Iniciar sesión", user: "Usuario", pass: "Contraseña", go: "Entrar", err: "Usuario o contraseña incorrectos." }}
  }};
  var lang = "{server_lang}";
  try {{ var v = localStorage.getItem("playline_lang"); if (L[v]) lang = v; }} catch (e) {{}}
  var d = L[lang];
  document.documentElement.lang = lang === "pt" ? "pt-BR" : lang;
  document.title = d.title;
  document.querySelectorAll("[data-l]").forEach(function (el) {{ el.textContent = d[el.getAttribute("data-l")]; }});
}})();
</script>
</body></html>"""


# ── Credential check (PBKDF2 em executor) ────────────────────────────────

async def _credentials_ok(username, password) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, app_settings.verify_credentials, username, password)


# ── Rotas ─────────────────────────────────────────────────────────────────

@router.get("/login")
async def login_page():
    return HTMLResponse(_build_login_html())


@router.post("/login")
async def login_submit(request: Request):
    ip = request.client.host if request.client else "unknown"
    if _login_blocked(ip):
        return HTMLResponse(_build_login_html(error=True), status_code=429)
    form = await request.form()
    if await _credentials_ok(form.get("username"), form.get("password")):
        _login_clear(ip)
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = time.time() + SESSION_TTL
        save_sessions(SESSIONS)
        resp = RedirectResponse(url="/", status_code=302)
        resp.set_cookie("playline_session", token, httponly=True, samesite="lax", max_age=SESSION_TTL)
        return resp
    _login_record_fail(ip)
    return HTMLResponse(_build_login_html(error=True), status_code=401)


@router.post("/api/login")
async def api_login(request: Request):
    """Login JSON para clientes externos (PlayIngest, etc.)."""
    ip = request.client.host if request.client else "unknown"
    if _login_blocked(ip):
        return JSONResponse({"ok": False, "error": "Muitas tentativas, aguarde"}, status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido"}, status_code=400)
    if await _credentials_ok(body.get("username"), body.get("password")):
        _login_clear(ip)
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = time.time() + SESSION_TTL
        save_sessions(SESSIONS)
        return JSONResponse({"ok": True, "token": token})
    _login_record_fail(ip)
    return JSONResponse({"ok": False, "error": "Credenciais inválidas"}, status_code=401)


@router.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("playline_session", "")
    SESSIONS.pop(token, None)
    save_sessions(SESSIONS)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("playline_session")
    return resp


@router.post("/api/settings/credentials")
async def change_credentials(request: Request):
    """Troca usuário e senha."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido", "code": "bad_request", "params": {}},
                            status_code=400)
    if not await _credentials_ok(body.get("current_username"), body.get("current_password")):
        return JSONResponse({"ok": False, "error": "Usuário ou senha atuais incorretos",
                             "code": "cred_wrong", "params": {}}, status_code=403)
    loop = asyncio.get_running_loop()
    try:
        username = await loop.run_in_executor(
            None, app_settings.set_credentials, body.get("new_username"), body.get("new_password"))
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc),
                             "code": getattr(exc, "code", "invalid_value"),
                             "params": getattr(exc, "params", {})}, status_code=400)
    keep = request_token(request)
    for tok in list(SESSIONS):
        if tok != keep:
            SESSIONS.pop(tok, None)
    save_sessions(SESSIONS)
    logger.info("Credenciais alteradas pela interface; %d sessão(ões) mantida(s)", len(SESSIONS))
    return JSONResponse({"ok": True, "username": username})


@router.post("/api/settings/language")
async def change_language(request: Request):
    """Idioma padrão da interface (config.json), usado por navegadores sem escolha própria."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        lang = app_settings.set_language(body.get("language"))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc), "code": getattr(exc, "code", "invalid_value"),
                             "params": getattr(exc, "params", {})}, status_code=400)
    return {"ok": True, "language": lang}


# ── Middleware ────────────────────────────────────────────────────────────

_PUBLIC_PATHS = ("/login", "/api/ping", "/api/login", "/setup", "/setup/logo",
                 "/static/styles/base.css", "/static/components/i18n.js")
_PUBLIC_PREFIXES = ("/api/setup/", "/static/setup/", "/static/i18n/")


class SessionAuth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if path in ("/", "/login") and request.method == "GET" and not app_settings.is_setup_done():
            return RedirectResponse(url="/setup", status_code=302)
        if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)
        token = request.cookies.get("playline_session")
        if token and SESSIONS.get(token, 0) > time.time():
            return await call_next(request)
        url_token = request.query_params.get("session_token")
        if url_token and SESSIONS.get(url_token, 0) > time.time():
            if request.url.path.startswith("/api/"):
                return await call_next(request)
            resp = RedirectResponse(url=request.url.path, status_code=302)
            resp.set_cookie("playline_session", url_token, httponly=True, samesite="lax", max_age=SESSION_TTL)
            return resp
        return RedirectResponse(url="/login", status_code=302)
