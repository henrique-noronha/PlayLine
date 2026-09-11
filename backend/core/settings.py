"""Configurações persistentes do PlayLine: credenciais de acesso e pasta da biblioteca.

Ficam em `config.json` ao lado do banco (`core.db.DB_PATH.parent`): no build
congelado ao lado do .exe, em dev em backend/core/, e nos testes no diretório
temporário do conftest sem patch extra. `PLAYLINE_CONFIG` no ambiente sobrescreve.

A senha nunca é gravada em texto: PBKDF2-HMAC-SHA256 com salt aleatório (stdlib,
sem dependência nova). Sem arquivo, ou sem credenciais nele, valem os padrões de
sempre: PLAYLINE_USER / PLAYLINE_PASS do ambiente, ou playline/playline.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Optional

from core import db as _db

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_PBKDF2_ITER = 200_000
USERNAME_MAX = 64
PASSWORD_MIN = 4
PASSWORD_MAX = 128
_WRITE_PROBE = ".playline_write_test"


# ── Arquivo ─────────────────────────────────────────────────────────────────

def config_path() -> Path:
    env = os.environ.get("PLAYLINE_CONFIG")
    if env:
        return Path(env)
    return Path(_db.DB_PATH).parent / "config.json"


def load() -> dict:
    p = config_path()
    try:
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("config.json ilegível (%s); usando padrões", exc)
        return {}


def save(data: dict) -> None:
    """Escrita atômica (tmp + replace) para nunca deixar um JSON pela metade."""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _update(**fields) -> dict:
    """Atualiza só as chaves informadas; valor None remove a chave."""
    with _LOCK:
        data = load()
        for key, value in fields.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        save(data)
        return data


# ── Credenciais ─────────────────────────────────────────────────────────────

def _default_username() -> str:
    return os.environ.get("PLAYLINE_USER", "playline")


def _default_password() -> str:
    return os.environ.get("PLAYLINE_PASS", "playline")


def _hash_password(password: str, salt: bytes, iterations: int = _PBKDF2_ITER) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def _stored_auth() -> Optional[dict]:
    auth = load().get("auth")
    if isinstance(auth, dict) and auth.get("username") and auth.get("password_hash") and auth.get("salt"):
        return auth
    return None


def has_custom_credentials() -> bool:
    return _stored_auth() is not None


def get_username() -> str:
    auth = _stored_auth()
    return auth["username"] if auth else _default_username()


def verify_credentials(username, password) -> bool:
    """Compara usuário e senha em tempo constante. Custa ~0,1s (PBKDF2) quando há
    credenciais gravadas: nas rotas async chamar via run_in_executor."""
    username = (username or "").strip()
    password = password or ""
    auth = _stored_auth()
    if auth:
        try:
            salt = bytes.fromhex(auth["salt"])
            iterations = int(auth.get("iterations") or _PBKDF2_ITER)
        except (ValueError, TypeError):
            return False
        user_ok = hmac.compare_digest(username.encode("utf-8"), str(auth["username"]).encode("utf-8"))
        pass_ok = hmac.compare_digest(_hash_password(password, salt, iterations), str(auth["password_hash"]))
        return user_ok and pass_ok
    user_ok = hmac.compare_digest(username.encode("utf-8"), _default_username().encode("utf-8"))
    pass_ok = hmac.compare_digest(password.encode("utf-8"), _default_password().encode("utf-8"))
    return user_ok and pass_ok


def validate_new_credentials(username, password) -> tuple[str, str]:
    username = (username or "").strip()
    password = password or ""
    if not username:
        raise ValueError("Informe o novo usuário")
    if len(username) > USERNAME_MAX:
        raise ValueError(f"O usuário deve ter no máximo {USERNAME_MAX} caracteres")
    if any(ch.isspace() for ch in username):
        raise ValueError("O usuário não pode conter espaços")
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"A nova senha deve ter pelo menos {PASSWORD_MIN} caracteres")
    if len(password) > PASSWORD_MAX:
        raise ValueError(f"A nova senha deve ter no máximo {PASSWORD_MAX} caracteres")
    return username, password


def set_credentials(username, password) -> str:
    """Grava novas credenciais (salt novo a cada troca). Retorna o usuário normalizado."""
    username, password = validate_new_credentials(username, password)
    salt = secrets.token_bytes(16)
    _update(auth={
        "username": username,
        "password_hash": _hash_password(password, salt),
        "salt": salt.hex(),
        "iterations": _PBKDF2_ITER,
    })
    logger.info("Credenciais de acesso atualizadas (usuário: %s)", username)
    return username


# ── Biblioteca ──────────────────────────────────────────────────────────────

def get_library_dir() -> Optional[Path]:
    raw = load().get("library_dir")
    return Path(raw) if raw else None


def set_library_dir(path: Optional[Path]) -> None:
    """None volta ao padrão (remove a chave)."""
    _update(library_dir=str(path) if path else None)


def validate_library_dir(raw: str) -> Path:
    """Valida a pasta digitada/escolhida e devolve o caminho resolvido.

    Faz I/O de disco (existe? consegue escrever?), que numa unidade de rede fora
    do ar pode demorar: chamar fora do event loop.
    """
    raw = (raw or "").strip().strip('"').strip()
    if not raw:
        raise ValueError("Informe o caminho da pasta")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise ValueError("O caminho precisa ser absoluto (ex.: D:\\Videos\\Biblioteca)")
    if any(part == ".." for part in p.parts):
        raise ValueError("Caminho inválido")
    if not p.exists():
        raise ValueError("A pasta não existe no servidor. Crie a pasta primeiro e tente de novo")
    if not p.is_dir():
        raise ValueError("O caminho aponta para um arquivo, não para uma pasta")
    probe = p / _WRITE_PROBE
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise ValueError(f"Sem permissão de escrita na pasta ({exc.strerror or exc})")
    return p.resolve()


# ── Transição entre clipes ──────────────────────────────────────────────────

TRANSITION_TYPES = ("cut", "fade")
TRANSITION_MIN = 0.2
TRANSITION_MAX = 3.0
_TRANSITION_DEFAULT = {"type": "cut", "duration": 0.5}


def normalize_transition(cfg, base: Optional[dict] = None) -> dict:
    """Valida {"type", "duration"}; chave ausente vem de `base` (ou do padrão)."""
    base = dict(base or _TRANSITION_DEFAULT)
    cfg = cfg if isinstance(cfg, dict) else {}
    t = cfg.get("type", base["type"])
    if t not in TRANSITION_TYPES:
        raise ValueError("Tipo de transição inválido (use 'cut' ou 'fade')")
    try:
        d = float(cfg.get("duration", base["duration"]))
    except (TypeError, ValueError):
        raise ValueError("Duração inválida")
    if not (TRANSITION_MIN <= d <= TRANSITION_MAX):
        raise ValueError(
            f"A duração do fade deve ficar entre {TRANSITION_MIN:g} e {TRANSITION_MAX:g} segundos")
    return {"type": t, "duration": round(d, 2)}


# ── Cidades do overlay de hora/temperatura ──────────────────────────────────
#
# A lista fica em config.json e é montada pelo operador na tela de Configurações
# (busca no geocoding da OpenWeatherMap). Guardar lat/lon junto do nome resolve a
# ambiguidade de homônimos: existem cinco "Palmas" no Brasil, e a consulta por
# nome pegava qualquer uma delas. Sem nada gravado, valem as capitais abaixo.

CITIES_MAX = 30
CITY_NAME_MAX = 64

_DEFAULT_CITIES = [
    ('Palmas', 'TO', -10.1838, -48.3336),
    ('Araguaína', 'TO', -7.1932, -48.2019),
    ('Araguatins', 'TO', -5.6529, -48.1162),
    ('Arapoema', 'TO', -7.6575, -49.0641),
    ('Augustinópolis', 'TO', -5.4662, -47.8898),
    ('Couto Magalhães', 'TO', -8.3606, -49.1774),
    ('Dianópolis', 'TO', -11.624, -46.8198),
    ('Gurupi', 'TO', -11.7279, -49.068),
    ('Luzimangues', 'TO', -10.1736, -48.4599),
    ('Nazaré', 'TO', -6.3733, -47.6633),
    ('Paraíso do Tocantins', 'TO', -10.1752, -48.8868),
    ('Porto Nacional', 'TO', -10.702, -48.4111),
    ('Praia Norte', 'TO', -5.3928, -47.8111),
    ('Sampaio', 'TO', -5.3542, -47.8782),
    ('Tocantinópolis', 'TO', -6.3281, -47.4218),
]


def default_cities() -> list[dict]:
    return [{"name": n, "state": uf, "lat": lat, "lon": lon}
            for n, uf, lat, lon in _DEFAULT_CITIES]


def city_key(city) -> str:
    """Identificador usado pela interface e pelo overlay: 'Palmas,TO'."""
    if isinstance(city, str):
        return city.strip()
    if not isinstance(city, dict):
        return ""            # None ou tipo inesperado: sem correspondência
    name = str(city.get("name", "")).strip()
    state = str(city.get("state", "")).strip().upper()
    return f"{name},{state}" if state else name


def normalize_city(city) -> dict:
    """Valida uma cidade vinda da interface. ValueError se inválida."""
    if not isinstance(city, dict):
        raise ValueError("Cidade em formato inválido")
    name = str(city.get("name", "")).strip()
    state = str(city.get("state", "")).strip().upper()
    if not name:
        raise ValueError("Cidade sem nome")
    if len(name) > CITY_NAME_MAX:
        raise ValueError(f"Nome de cidade muito longo (máximo {CITY_NAME_MAX} caracteres)")
    if state and (len(state) != 2 or not state.isalpha()):
        raise ValueError(f"Estado inválido em {name!r} (use a sigla, por exemplo TO)")
    try:
        lat = float(city["lat"])
        lon = float(city["lon"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"Coordenadas ausentes ou inválidas em {name!r}")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Coordenadas fora de faixa em {name!r}")
    return {"name": name, "state": state, "lat": round(lat, 4), "lon": round(lon, 4)}


def get_cities() -> list[dict]:
    raw = load().get("cities")
    if not isinstance(raw, list) or not raw:
        return default_cities()
    out, seen = [], set()
    for item in raw:
        try:
            c = normalize_city(item)
        except ValueError:
            continue          # entrada corrompida: ignora em vez de derrubar o overlay
        k = city_key(c).lower()
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out or default_cities()


def set_cities(cities) -> list[dict]:
    """Grava a lista (ordem preservada, sem duplicatas). ValueError se inválida."""
    if not isinstance(cities, list):
        raise ValueError("Lista de cidades inválida")
    if not cities:
        raise ValueError("Mantenha pelo menos uma cidade na lista")
    if len(cities) > CITIES_MAX:
        raise ValueError(f"O limite é de {CITIES_MAX} cidades")
    out, seen = [], set()
    for item in cities:
        c = normalize_city(item)
        k = city_key(c).lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    _update(cities=out)
    logger.info("Lista de cidades atualizada: %d cidade(s)", len(out))
    return out


def reset_cities() -> list[dict]:
    """Remove a lista gravada: volta a valer a lista padrão (capitais)."""
    _update(cities=None)
    logger.info("Lista de cidades restaurada para o padrão")
    return default_cities()


def find_city(city) -> Optional[dict]:
    """Acha a cidade salva a partir de 'Palmas,TO' (ou só 'Palmas'). None se não houver."""
    alvo = city_key(city).strip().lower()
    if not alvo:
        return None
    cidades = get_cities()
    for c in cidades:
        if city_key(c).lower() == alvo:
            return c
    nome = alvo.split(",")[0].strip()          # sem a sigla do estado
    for c in cidades:
        if c["name"].lower() == nome:
            return c
    return None


def get_transition() -> dict:
    try:
        return normalize_transition(load().get("transition"))
    except ValueError:
        return dict(_TRANSITION_DEFAULT)


def set_transition(cfg) -> dict:
    """Atualização parcial: {"type": "fade"} mantém a duração, {"duration": 1} mantém o tipo."""
    new = normalize_transition(cfg, base=get_transition())
    _update(transition=new)
    return new
