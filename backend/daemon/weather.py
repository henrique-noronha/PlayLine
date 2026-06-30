"""Fetch de temperatura via wttr.in com cache de 60s."""

import asyncio
import logging
import time
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("mpv_daemon")

_TTL = 60.0

_cache_value: Optional[str] = None
_cache_time:  float = 0.0
_cache_city:  str   = ""


async def get_temperature(city: str) -> Optional[str]:
    """Retorna temperatura como string (ex: '+28°C') ou None em falha."""
    global _cache_value, _cache_time, _cache_city

    if city != _cache_city:
        _cache_value = None
        _cache_time  = 0.0
        _cache_city  = city

    now = time.monotonic()
    if _cache_value is not None and (now - _cache_time) < _TTL:
        return _cache_value

    try:
        url = f"https://wttr.in/{quote(city)}?format=%t"
        loop = asyncio.get_event_loop()
        val  = await loop.run_in_executor(None, _fetch, url)
        if val:
            _cache_value = val
            _cache_time  = now
        return _cache_value
    except Exception as exc:
        logger.warning("[weather] indisponível: %s", exc)
        return _cache_value   # retorna valor antigo do cache, se houver


def _fetch(url: str) -> Optional[str]:
    from urllib.request import urlopen
    try:
        with urlopen(url, timeout=5) as resp:
            val = resp.read().decode("utf-8").strip()
            return val if val else None
    except Exception:
        return None
