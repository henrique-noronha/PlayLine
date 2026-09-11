"""Testes do fade para preto (daemon/transition.py) com um MPV falso."""

import time

import pytest

from daemon import transition
from daemon.transition import Fader


class FakeMPV:
    def __init__(self, duration=10.0):
        self.volume = 100.0
        self.duration = duration
        self.commands = []

    def command(self, *args):
        self.commands.append(args)

    def overlays(self):
        """Formatos enviados ao osd-overlay do fader ("ass-events" ou "none")."""
        return [c[2] for c in self.commands if c[0] == "osd-overlay" and c[1] == transition.OSD_ID]


@pytest.fixture
def fx():
    m = FakeMPV()
    f = Fader(lambda: m, user_volume=80.0)
    f.configure({"type": "fade", "duration": 0.1})
    return m, f


def _settle(sec=0.3):
    time.sleep(sec)


# ── configuração / resolução ────────────────────────────────────────────────

def test_resolve_override_e_global(fx):
    _, f = fx
    assert f.resolve(None) is True
    assert f.resolve("cut") is False
    assert f.resolve("fade") is True
    f.configure({"type": "cut"})
    assert f.resolve(None) is False
    assert f.resolve("fade") is True
    assert f.resolve("qualquer") is False


def test_configure_valida_e_mantem_o_resto():
    f = Fader(lambda: None)
    with pytest.raises(ValueError):
        f.configure({"type": "dissolve"})
    assert f.configure({"duration": 2}) == {"type": "cut", "duration": 2.0}
    assert f.configure({"type": "fade"}) == {"type": "fade", "duration": 2.0}


# ── fade out / fade in ──────────────────────────────────────────────────────

def test_fade_out_bloqueante_chega_no_preto_e_zera_volume(fx):
    m, f = fx
    f.fade_out_blocking()
    assert f.is_black
    assert m.volume == 0
    last = m.commands[-1]
    assert last[0] == "osd-overlay" and last[2] == "ass-events"
    assert "1a&H00&" in last[3]          # alpha 00 = opaco


def test_play_com_fade_do_ocioso_comeca_preto_e_fade_in_no_file_loaded(fx):
    m, f = fx
    f.on_play("b.mp4", None, incoming_fade=True)   # nada no ar: já fica preto
    assert f.is_black and m.volume == 0
    f.on_file_loaded("b.mp4")
    _settle()
    assert f.alpha == 0
    assert m.volume == pytest.approx(80.0)
    assert m.overlays()[-1] == "none"


def test_play_com_corte_nao_toca_na_tela(fx):
    m, f = fx
    f.on_play("b.mp4", None, incoming_fade=False)
    f.on_file_loaded("b.mp4")
    assert f.alpha == 0 and not m.commands


def test_fade_out_automatico_dispara_uma_vez_perto_do_fim(fx):
    m, f = fx
    f.on_play("a.mp4", None, incoming_fade=False)
    f.on_file_loaded("a.mp4")
    f.on_time_pos(5.0, lambda: 10.0)
    assert f.alpha == 0 and not m.commands        # longe do fim: nada
    f.on_time_pos(9.92, lambda: 10.0)
    _settle()
    assert f.is_black and m.volume == 0
    n = len(m.commands)
    f.on_time_pos(9.95, lambda: 10.0)             # não redispara
    _settle(0.05)
    assert len(m.commands) == n
    f.on_file_loaded("b.mp4")                     # MPV saltou pro próximo: fade in
    _settle()
    assert f.alpha == 0 and m.volume == pytest.approx(80.0)


def test_usa_end_do_recorte_em_vez_da_duracao(fx):
    m, f = fx
    f.on_play("a.mp4", 4.0, incoming_fade=False)
    f.on_file_loaded("a.mp4")
    f.on_time_pos(3.0, lambda: 60.0)
    assert f.alpha == 0
    f.on_time_pos(3.93, lambda: 60.0)
    _settle()
    assert f.is_black


def test_sem_duracao_nao_dispara(fx):          # live / captura
    m, f = fx
    f.on_file_loaded("av://dshow:video=cam")
    f.on_time_pos(1000.0, lambda: None)
    assert f.alpha == 0 and not m.commands


def test_override_cut_do_proximo_item_desliga_o_fade_out(fx):
    m, f = fx
    f.on_file_loaded("a.mp4")
    f.set_next_boundary("cut")
    f.on_time_pos(9.95, lambda: 10.0)
    assert f.alpha == 0 and not m.commands
    f.set_next_boundary("fade")
    f.on_time_pos(9.95, lambda: 10.0)
    _settle()
    assert f.is_black


def test_global_cut_com_override_fade_no_proximo(fx):
    m, f = fx
    f.configure({"type": "cut"})
    f.on_file_loaded("a.mp4")
    f.set_next_boundary("fade")
    f.on_time_pos(9.95, lambda: 10.0)
    _settle()
    assert f.is_black


# ── cancelamentos e estado ──────────────────────────────────────────────────

def test_cancel_and_clear_restaura_e_permite_redisparo(fx):
    m, f = fx
    f.on_file_loaded("a.mp4")
    f.on_time_pos(9.95, lambda: 10.0)
    _settle()
    assert f.is_black
    f.cancel_and_clear()                          # pausa / seek
    assert f.alpha == 0
    assert m.volume == pytest.approx(80.0)
    assert m.overlays()[-1] == "none"
    f.on_time_pos(9.96, lambda: 10.0)             # retomou faltando pouco: fade de novo
    _settle()
    assert f.is_black


def test_idle_limpa_preto_e_volume(fx):
    m, f = fx
    f.fade_out_blocking()
    f.on_idle()                                   # fim do roteiro / stop
    assert f.alpha == 0 and m.volume == pytest.approx(80.0)


def test_volume_do_operador_durante_o_preto(fx):
    m, f = fx
    f.fade_out_blocking()
    f.set_user_volume(120)
    assert m.volume == 0                          # continua mudo enquanto está preto
    f.cancel_and_clear()
    assert m.volume == pytest.approx(120.0)


def test_file_loaded_sem_fade_pendente_limpa_preto_que_sobrou(fx):
    m, f = fx
    f.fade_out_blocking()
    f.on_file_loaded("c.mp4")                     # corte seco depois de um preto
    assert f.alpha == 0 and m.volume == pytest.approx(80.0)


def test_rebind_zera_estado_sem_tocar_no_mpv_antigo(fx):
    m, f = fx
    f.fade_out_blocking()
    n = len(m.commands)
    f.rebind()
    assert f.alpha == 0 and not f.is_black and len(m.commands) == n


def test_sem_mpv_nao_quebra():
    f = Fader(lambda: None)
    f.configure({"type": "fade", "duration": 0.05})
    f.fade_out_blocking()
    f.cancel_and_clear()
    assert f.alpha == 0


def test_ass_alpha_extremos():
    assert "1a&HFF&" in transition._ass_black(0.0)   # transparente
    assert "1a&H00&" in transition._ass_black(1.0)   # opaco
    assert transition._audio_gain(0.0) == 1.0
    assert transition._audio_gain(1.0) == 0.0
    assert 0 < transition._audio_gain(0.5) < 0.5     # curva quadrática
