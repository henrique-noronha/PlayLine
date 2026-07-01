"""Fetch de temperatura via OpenWeatherMap com cache de 60s."""

import asyncio
import json
import logging
import time
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("mpv_daemon")

_TTL     = 60.0
_API_KEY = "f69ea9de2f716268934177c04852b89b"

_cache_value: Optional[str] = None
_cache_time:  float = 0.0
_cache_city:  str   = ""


def _owm_query(city: str) -> str:
    """Converte 'Palmas,TO' → 'Palmas,BR' (OWM usa código de país, não estado)."""
    name = city.split(",")[0].strip()
    return f"{quote(name)},BR"


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
        url = f"https://api.openweathermap.org/data/2.5/weather?q={_owm_query(city)}&appid={_API_KEY}&units=metric"
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
            name_found = data.get("name", "?")
            country    = data.get("sys", {}).get("country", "?")
            logger.info("[weather] OWM: %.1f°C (%s, %s)", temp, name_found, country)
            return f"{round(temp)}°C"
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
