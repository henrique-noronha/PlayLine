"""Fetch de temperatura via OpenWeatherMap com cache de 60s."""

import asyncio
import json
import logging
import time
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("mpv_daemon")

_TTL     = 900.0
_API_KEY = "f69ea9de2f716268934177c04852b89b"

_cache_value: Optional[str] = None
_cache_time:  float = 0.0
_cache_city:  str   = ""

_CITY_COORDS: dict[str, tuple[float, float]] = {
    "Palmas,TO":                (-10.1838, -48.3336),
    "Araguaína,TO":             ( -7.1932, -48.2019),
    "Araguatins,TO":            ( -5.6529, -48.1162),
    "Arapoema,TO":              ( -7.6575, -49.0641),
    "Augustinópolis,TO":        ( -5.4662, -47.8898),
    "Couto Magalhães,TO":       ( -8.3606, -49.1774),
    "Dianópolis,TO":            (-11.6240, -46.8198),
    "Gurupi,TO":                (-11.7279, -49.0680),
    "Luzimangues,TO":           (-10.1736, -48.4599),
    "Nazaré,TO":                ( -6.3733, -47.6633),
    "Paraíso do Tocantins,TO":  (-10.1752, -48.8868),
    "Porto Nacional,TO":        (-10.7020, -48.4111),
    "Praia Norte,TO":           ( -5.3928, -47.8111),
    "Sampaio,TO":               ( -5.3542, -47.8782),
    "Tocantinópolis,TO":        ( -6.3281, -47.4218),
}


async def get_temperature(city: str) -> Optional[str]:
    """Retorna temperatura como string (ex: '24°C') ou None em falha."""
    global _cache_value, _cache_time, _cache_city

    if city != _cache_city:
        _cache_value = None
        _cache_time  = 0.0
        _cache_city  = city

    now = time.monotonic()
    if _cache_value is not None and (now - _cache_time) < _TTL:
        return _cache_value

    try:
        coords = _CITY_COORDS.get(city)
        if coords:
            lat, lon = coords
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={_API_KEY}&units=metric"
        else:
            name = city.split(",")[0].strip()
            url = f"https://api.openweathermap.org/data/2.5/weather?q={quote(name)},BR&appid={_API_KEY}&units=metric"
        loop = asyncio.get_event_loop()
        val  = await loop.run_in_executor(None, _fetch, url, city)
        if val:
            _cache_value = val
            _cache_time  = now
        return _cache_value
    except Exception as exc:
        logger.warning("[weather] indisponível: %s", exc)
        return _cache_value


def _fetch(url: str, city: str) -> Optional[str]:
    from urllib.request import urlopen
    from urllib.error import HTTPError
    try:
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            temp = data.get("main", {}).get("temp")
            if temp is None:
                logger.warning("[weather] OWM sem 'main.temp': %s", data)
                return None
            corrected  = round(temp - 1)
            name_found = data.get("name", "?")
            country    = data.get("sys", {}).get("country", "?")
            logger.info("[weather] OWM: %.1f°C → %d°C (corrigido) (%s, %s)", temp, corrected, name_found, country)
            return f"{corrected}°C"
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        logger.warning("[weather] OWM HTTP %d — usando fallback wttr.in: %s", exc.code, body[:120])
        return _fetch_wttr(city)
    except Exception as exc:
        logger.warning("[weather] OWM falhou (%s) — usando fallback wttr.in", exc)
        return _fetch_wttr(city)


def _fetch_wttr(city: str) -> Optional[str]:
    """Fallback: obtém temperatura via wttr.in quando OWM não está disponível."""
    from urllib.request import urlopen
    try:
        url = f"https://wttr.in/{quote(city)}?format=%t"
        with urlopen(url, timeout=5) as resp:
            val = resp.read().decode("utf-8").strip().lstrip("+")
            logger.info("[weather] wttr.in fallback: %s", val)
            return val if val else None
    except Exception as exc:
        logger.warning("[weather] wttr.in também falhou: %s", exc)
        return None
