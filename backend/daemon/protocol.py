"""Protocolo TCP do daemon: parsing de eventos do MPV."""


def parse_end_reason(event) -> str:
    """Converte o evento end-file do MPV em 'eof', 'stop' ou 'error'."""
    try:
        raw = None
        if isinstance(event, dict):
            raw = event.get("reason")
            if raw is None:
                evt = event.get("event")
                raw = (
                    evt.get("reason")
                    if isinstance(evt, dict)
                    else getattr(evt, "reason", None)
                )
        else:
            raw = getattr(event, "reason", None)
            if raw is None:
                data = getattr(event, "data", None)
                if data is not None:
                    raw = getattr(data, "reason", None)

        s = str(raw).lower() if raw is not None else ""
        try:
            r = int(raw)
        except (TypeError, ValueError):
            r = -1

        if r in (2, 3) or "stop" in s or "quit" in s:
            return "stop"
        if r == 4 or "error" in s:
            return "error"
        return "eof"
    except Exception:
        return "eof"
