"""Gerenciamento do checkpoint de posição para retomada após crash."""

import json
import logging
from pathlib import Path

logger = logging.getLogger("mpv_daemon")


def write(checkpoint_path: Path, playing_path: str) -> None:
    """Cria/substitui o checkpoint com posição zero para o arquivo em reprodução."""
    try:
        checkpoint_path.write_text(
            json.dumps({"path": playing_path, "position": 0.0}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def flush(checkpoint_path: Path, position: float) -> bool:
    """Atualiza a posição no checkpoint existente. Retorna True se salvou."""
    try:
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        data["position"] = position
        checkpoint_path.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def clear(checkpoint_path: Path) -> None:
    """Remove o arquivo de checkpoint."""
    try:
        checkpoint_path.unlink(missing_ok=True)
    except Exception:
        pass
