"""Rotas de cidades e temperatura (overlay de hora/clima)."""

import asyncio
import json
import logging
from urllib.parse import quote
from urllib.request import urlopen

from fastapi import APIRouter

from core import settings as app_settings
from api.helpers import _coded_error, _settings_error

logger = logging.getLogger(__name__)

router = APIRouter()

_manager = None


def setup(manager):
    global _manager
    _manager = manager


_GEO_URL = "https://api.openweathermap.org/geo/1.0/direct"
_API_KEY = "f69ea9de2f716268934177c04852b89b"


@router.get("/api/temperature")
async def get_temperature(city: str = "Palmas,TO"):
    """Proxy para OpenWeatherMap — retorna temperatura como texto (ex: '24°C')."""
    from fastapi.responses import PlainTextResponse

    def _fetch():
        saved = app_settings.find_city(city)
        if saved:
            loc = f"lat={saved['lat']}&lon={saved['lon']}"
        else:
            loc = f"q={quote(city.split(',')[0].strip())},BR"
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?{loc}&appid={_API_KEY}&units=metric"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                temp = data.get("main", {}).get("temp")
                if temp is not None:
                    corrected = round(temp - 1)
                    logger.info("[weather] OWM: %.1f°C → %d°C (corrigido) (%s)", temp, corrected, city)
                    return f"{corrected}°C"
        except Exception as e:
            logger.warning("[weather] OWM falhou: %s — tentando wttr.in", e)
        try:
            url = f"https://wttr.in/{quote(city)}?format=%t"
            with urlopen(url, timeout=5) as resp:
                val = resp.read().decode("utf-8").strip().lstrip("+")
                logger.info("[weather] wttr.in fallback: %s", val)
                return val
        except Exception as e:
            logger.warning("[weather] wttr.in também falhou: %s", e)
            return ""

    loop = asyncio.get_running_loop()
    val = await loop.run_in_executor(None, _fetch)
    return PlainTextResponse(val or "—")


@router.get("/api/cities")
async def list_cities():
    return {"cities": app_settings.get_cities(), "max": app_settings.CITIES_MAX}


@router.put("/api/cities")
async def save_cities(body: dict):
    """Grava a lista montada na tela de Configurações (no máximo CITIES_MAX)."""
    if body.get("reset"):
        cities = app_settings.reset_cities()
    else:
        try:
            cities = app_settings.set_cities(body.get("cities"))
        except ValueError as exc:
            return _settings_error(exc)
    if _manager:
        await _manager.broadcast({"event": "cities_changed", "cities": cities})
    return {"ok": True, "cities": cities}


@router.get("/api/cities/search")
async def search_cities(q: str = "", limit: int = 6):
    """Busca no geocoding da OpenWeatherMap para o operador escolher a cidade certa."""
    termo = (q or "").strip()
    if len(termo) < 2:
        return {"results": []}
    limit = max(1, min(10, int(limit)))

    def _search():
        url = f"{_GEO_URL}?q={quote(termo)},BR&limit={limit}&appid={_API_KEY}"
        with urlopen(url, timeout=6) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        data = await asyncio.get_running_loop().run_in_executor(None, _search)
    except Exception as exc:
        logger.warning("[cities] busca falhou: %s", exc)
        return _coded_error(502, "city_search_unavailable",
                            "Não foi possível consultar a busca de cidades. Verifique a conexão com a internet")

    _UF = {
        "Acre": "AC", "Alagoas": "AL", "Amapá": "AP", "Amazonas": "AM", "Bahia": "BA",
        "Ceará": "CE", "Federal District": "DF", "Distrito Federal": "DF",
        "Espírito Santo": "ES", "Goiás": "GO", "Maranhão": "MA", "Mato Grosso": "MT",
        "Mato Grosso do Sul": "MS", "Minas Gerais": "MG", "Pará": "PA", "Paraíba": "PB",
        "Paraná": "PR", "Pernambuco": "PE", "Piauí": "PI", "Rio de Janeiro": "RJ",
        "Rio Grande do Norte": "RN", "Rio Grande do Sul": "RS", "Rondônia": "RO",
        "Roraima": "RR", "Santa Catarina": "SC", "São Paulo": "SP", "Sergipe": "SE",
        "Tocantins": "TO",
    }
    results, vistos = [], set()
    for item in data if isinstance(data, list) else []:
        if item.get("country") != "BR":
            continue
        estado = item.get("state") or ""
        sigla = _UF.get(estado, estado[:2].upper() if estado else "")
        nome = (item.get("name") or "").strip()
        if not nome:
            continue
        chave = f"{nome},{sigla}".lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        results.append({"name": nome, "state": sigla, "state_name": estado,
                        "lat": round(float(item["lat"]), 4), "lon": round(float(item["lon"]), 4)})
    return {"results": results}
