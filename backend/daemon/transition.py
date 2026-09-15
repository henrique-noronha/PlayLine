"""Transição entre clipes: fade para preto (vídeo + áudio) em cima do MPV.

O MPV tem um único decodificador, então não existe crossfade A/B. O que dá para
fazer com robustez, e é a transição suave padrão de playout, é fade para preto:
fade out no fim do clipe, preto cobrindo o instante da troca, fade in no início
do próximo.

Vídeo: retângulo preto de tela cheia via `osd-overlay` (ASS) com o alpha animado
em ~30 passos. Custa ~0,1 ms por passo, não mexe na cadeia de filtros, persiste
através da troca de arquivo (inclusive no append gapless) e renderiza acima dos
`overlay-add` (logos e relógio escurecem junto).

Áudio: rampa da propriedade `volume` a partir do nível do operador, com curva
quadrática (mais próxima da percepção do que a linear).

Regras (o daemon chama os métodos on_*):
- automático: `on_time_pos` dispara o fade out `duration` s antes do fim do
  clipe (fim efetivo = `end` do recorte, senão `duration` do arquivo). O clipe
  termina no mesmo instante de sempre, então a grade horária não muda.
- manual (play/stop com algo no ar): o daemon chama `fade_out_blocking()`
  antes de trocar.
- `on_file_loaded`: fade in se a fronteira era fade; senão limpa qualquer preto.
- pause/seek/idle: `cancel_and_clear()` (tela e volume de volta; o fade
  automático pode disparar de novo se ainda faltar menos que `duration`).
- por item: `set_next_boundary("fade"|"cut"|None)` e `resolve(override)`;
  None segue a configuração global.
"""

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("mpv_daemon")

OSD_ID = 63                   # id do osd-overlay (namespace próprio, separado dos overlay-add)
_ASS_W, _ASS_H = 1920, 1080   # resolução lógica do ASS; a libass escala para a janela
_FPS = 30
_LEAD_SEC = 0.05              # folga para a latência do observer de time-pos
TYPES = ("cut", "fade")


def _ass_black(alpha: float) -> str:
    """Retângulo preto cobrindo a tela; alpha 0..1 (no ASS, 00 = opaco, FF = transparente)."""
    a = int(round(255 * (1.0 - max(0.0, min(1.0, alpha)))))
    return ("{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H000000&\\1a&H%02X&\\p1}"
            "m 0 0 l %d 0 %d %d 0 %d{\\p0}" % (a, _ASS_W, _ASS_W, _ASS_H, _ASS_H))


def _audio_gain(alpha: float) -> float:
    """Ganho 0..1 para um alpha de preto 0..1 (quadrático: some suave no fim)."""
    x = 1.0 - max(0.0, min(1.0, alpha))
    return x * x


class Fader:
    def __init__(self, get_mpv: Callable, user_volume: float = 100.0):
        self._get_mpv = get_mpv            # callable -> instância mpv viva, ou None
        self._user_volume = float(user_volume)
        self.config = {"type": "cut", "duration": 0.5}
        self.alpha = 0.0                   # 0 = transparente, 1 = preto
        self._gen = 0                      # invalida a animação anterior
        self._lock = threading.Lock()
        self._clip_end: Optional[float] = None          # fim efetivo do clipe atual (end do recorte)
        self._pending_clip_end: Optional[float] = None  # idem, do clipe que o play acabou de pedir
        self._next_override: Optional[str] = None       # "fade"/"cut" do próximo item, None = global
        self._pending_fade_in = False
        self._fired_for: Optional[str] = None           # path cujo fade out automático já disparou
        self._current_path: Optional[str] = None

    # ── configuração ─────────────────────────────────────────────────────

    def configure(self, cfg: dict) -> dict:
        t = cfg.get("type", self.config["type"])
        if t not in TYPES:
            raise ValueError(f"tipo de transição inválido: {t!r}")
        d = float(cfg.get("duration", self.config["duration"]))
        d = max(0.1, min(10.0, d))
        self.config = {"type": t, "duration": d}
        return dict(self.config)

    @property
    def duration(self) -> float:
        return self.config["duration"]

    def is_fade_global(self) -> bool:
        return self.config["type"] == "fade"

    def resolve(self, override) -> bool:
        """True se a fronteira deve ser fade: override do item ("fade"/"cut") ou o global."""
        if override in TYPES:
            return override == "fade"
        return self.is_fade_global()

    @property
    def is_black(self) -> bool:
        return self.alpha >= 0.999

    def set_user_volume(self, vol: float) -> None:
        """Nível do operador mudou: reaplica com o ganho atual (0 se estiver no preto)."""
        self._user_volume = float(vol)
        self._apply(self.alpha)

    # ── ciclo do clipe ───────────────────────────────────────────────────

    def set_next_boundary(self, override) -> None:
        self._next_override = override if override in TYPES else None

    def on_play(self, path: str, end_time, incoming_fade: bool) -> None:
        """Chamado logo antes do loadfile (depois do fade out manual, se houve)."""
        self._pending_clip_end = float(end_time) if end_time else None
        self._pending_fade_in = bool(incoming_fade)
        self._next_override = None
        self._fired_for = None
        if incoming_fade and not self.is_black:
            # Nada no ar (ocioso): começa do preto para o fade in ter de onde vir
            with self._lock:
                self._gen += 1
            self._apply(1.0)

    def on_file_loaded(self, path: str) -> None:
        self._current_path = path
        self._clip_end = self._pending_clip_end
        self._pending_clip_end = None
        self._fired_for = None
        if self._pending_fade_in:
            self._pending_fade_in = False
            self.fade_to(0.0, self.duration)
        elif self.alpha > 0:
            self.cancel_and_clear()

    def on_time_pos(self, pos, duration_getter: Callable) -> None:
        """Fade out automático perto do fim (só clipes com fim conhecido)."""
        if pos is None or self._fired_for == self._current_path:
            return
        if not self.resolve(self._next_override):
            return
        end = self._clip_end
        if not end:
            try:
                end = duration_getter()
            except Exception:
                end = None
        if not end or end <= 0:
            return  # live/captura: sem fim conhecido
        remaining = float(end) - float(pos)
        if remaining <= self.duration + _LEAD_SEC:
            self._fired_for = self._current_path
            self._pending_fade_in = True
            self.fade_to(1.0, max(0.1, min(self.duration, remaining)))
            logger.info("[transition] fade out automático a %.2fs do fim", remaining)

    def on_idle(self) -> None:
        """MPV ficou ocioso (fim do roteiro, stop): não deixa preto nem volume zerado para trás."""
        if self.alpha > 0 or self._pending_fade_in:
            self.cancel_and_clear()

    def rebind(self) -> None:
        """MPV reinicializado: o overlay antigo morreu com a instância; zera o estado."""
        with self._lock:
            self._gen += 1
        self.alpha = 0.0
        self._pending_fade_in = False
        self._fired_for = None
        self._clip_end = None
        self._pending_clip_end = None
        self._current_path = None

    # ── ações ────────────────────────────────────────────────────────────

    def fade_out_blocking(self) -> None:
        """Vai até o preto e só retorna quando chegou (troca manual, stop)."""
        if self.is_black:
            return
        self.fade_to(1.0, self.duration, wait=True)

    def cancel_and_clear(self) -> None:
        """Interrompe qualquer rampa, remove o preto e devolve o volume do operador."""
        with self._lock:
            self._gen += 1
        self._pending_fade_in = False
        self._fired_for = None
        self._apply(0.0)

    # ── animação ─────────────────────────────────────────────────────────

    def fade_to(self, target: float, dur: float, wait: bool = False) -> None:
        with self._lock:
            self._gen += 1
            gen = self._gen
        start = self.alpha
        steps = max(1, int(round(dur * _FPS)))

        def run():
            t0 = time.perf_counter()
            for i in range(1, steps + 1):
                if self._gen != gen:
                    return
                self._apply(start + (target - start) * (i / steps))
                delay = t0 + dur * i / steps - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)

        th = threading.Thread(target=run, name="fader", daemon=True)
        th.start()
        if wait:
            th.join(dur + 1.0)

    def _apply(self, alpha: float) -> None:
        self.alpha = max(0.0, min(1.0, alpha))
        mpv = self._get_mpv()
        if mpv is None:
            return
        try:
            if self.alpha <= 0.0:
                mpv.command("osd-overlay", OSD_ID, "none", "", _ASS_W, _ASS_H, 0, "no", "no")
            else:
                mpv.command("osd-overlay", OSD_ID, "ass-events", _ass_black(self.alpha),
                            _ASS_W, _ASS_H, 0, "no", "no")
            mpv.volume = self._user_volume * _audio_gain(self.alpha)
        except Exception as exc:
            logger.debug("[transition] apply falhou: %s", exc)
