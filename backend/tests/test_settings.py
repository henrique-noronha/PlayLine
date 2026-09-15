"""Testes de core/settings.py: credenciais persistidas e pasta da biblioteca."""

import json

import pytest

from core import settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PLAYLINE_USER", raising=False)
    monkeypatch.delenv("PLAYLINE_PASS", raising=False)
    monkeypatch.delenv("PLAYLINE_CONFIG", raising=False)


# ── Arquivo ─────────────────────────────────────────────────────────────────

def test_config_fica_ao_lado_do_banco(use_temp_db):
    assert settings.config_path() == use_temp_db.parent / "config.json"


def test_env_playline_config_sobrescreve(monkeypatch, tmp_path):
    alvo = tmp_path / "outro" / "cfg.json"
    monkeypatch.setenv("PLAYLINE_CONFIG", str(alvo))
    assert settings.config_path() == alvo
    settings.set_library_dir(tmp_path)
    assert alvo.exists()


def test_config_corrompido_cai_no_padrao():
    settings.config_path().write_text("{nao é json", encoding="utf-8")
    assert settings.verify_credentials("playline", "playline")
    assert settings.get_library_dir() is None


# ── Credenciais ─────────────────────────────────────────────────────────────

def test_padrao_sem_arquivo():
    assert not settings.has_custom_credentials()
    assert settings.get_username() == "playline"
    assert settings.verify_credentials("playline", "playline")
    assert not settings.verify_credentials("playline", "errada")
    assert not settings.verify_credentials("outro", "playline")
    assert not settings.verify_credentials(None, None)


def test_padrao_vem_do_ambiente(monkeypatch):
    monkeypatch.setenv("PLAYLINE_USER", "op")
    monkeypatch.setenv("PLAYLINE_PASS", "segredo")
    assert settings.get_username() == "op"
    assert settings.verify_credentials("op", "segredo")
    assert not settings.verify_credentials("playline", "playline")


def test_set_credentials_persiste_e_valida():
    settings.set_credentials("mestre", "nova1234")
    assert settings.has_custom_credentials()
    assert settings.get_username() == "mestre"
    assert settings.verify_credentials("mestre", "nova1234")
    assert not settings.verify_credentials("mestre", "playline")
    assert not settings.verify_credentials("playline", "nova1234")
    assert not settings.verify_credentials("mestre", "")

    raw = json.loads(settings.config_path().read_text(encoding="utf-8"))
    assert "nova1234" not in json.dumps(raw)          # senha nunca em texto
    assert raw["auth"]["username"] == "mestre"
    assert len(raw["auth"]["salt"]) == 32              # 16 bytes em hex


def test_set_credentials_normaliza_usuario():
    assert settings.set_credentials("  tv  ", "abcd") == "tv"
    assert settings.verify_credentials("tv", "abcd")
    assert settings.verify_credentials(" tv ", "abcd")


@pytest.mark.parametrize("user,pw,msg", [
    ("",           "abcd",    "usuário"),
    ("com espaço", "abcd",    "espaços"),
    ("x" * 65,     "abcd",    "máximo"),
    ("ok",         "abc",     "pelo menos"),
    ("ok",         "x" * 129, "máximo"),
])
def test_set_credentials_rejeita_invalidos(user, pw, msg):
    with pytest.raises(ValueError, match=msg):
        settings.set_credentials(user, pw)
    assert not settings.has_custom_credentials()


def test_salt_novo_a_cada_troca():
    settings.set_credentials("a", "mesma")
    h1 = json.loads(settings.config_path().read_text(encoding="utf-8"))["auth"]["password_hash"]
    settings.set_credentials("a", "mesma")
    h2 = json.loads(settings.config_path().read_text(encoding="utf-8"))["auth"]["password_hash"]
    assert h1 != h2
    assert settings.verify_credentials("a", "mesma")


def test_auth_incompleto_no_arquivo_cai_no_padrao():
    settings.save({"auth": {"username": "x"}})     # sem hash/salt
    assert not settings.has_custom_credentials()
    assert settings.verify_credentials("playline", "playline")


# ── Biblioteca ──────────────────────────────────────────────────────────────

def test_library_dir_round_trip(tmp_path):
    assert settings.get_library_dir() is None
    settings.set_library_dir(tmp_path / "midia")
    assert settings.get_library_dir() == tmp_path / "midia"
    settings.set_library_dir(None)
    assert settings.get_library_dir() is None


def test_library_nao_apaga_credenciais(tmp_path):
    settings.set_credentials("u", "senha1")
    settings.set_library_dir(tmp_path)
    assert settings.verify_credentials("u", "senha1")
    assert settings.get_library_dir() == tmp_path


def test_validate_library_dir_aceita_pasta_existente(tmp_path):
    d = tmp_path / "Videos"
    d.mkdir()
    assert settings.validate_library_dir(str(d)) == d.resolve()
    # aspas e espaços colados do Explorer ("Copiar como caminho")
    assert settings.validate_library_dir(f'  "{d}"  ') == d.resolve()
    assert not (d / settings._WRITE_PROBE).exists()   # arquivo de sondagem removido


@pytest.mark.parametrize("raw,msg", [
    ("",           "Informe"),
    ("   ",        "Informe"),
    ("Biblioteca", "absoluto"),
])
def test_validate_library_dir_rejeita(raw, msg):
    with pytest.raises(ValueError, match=msg):
        settings.validate_library_dir(raw)


def test_validate_library_dir_inexistente_ou_arquivo(tmp_path):
    with pytest.raises(ValueError, match="não existe"):
        settings.validate_library_dir(str(tmp_path / "nada"))
    f = tmp_path / "video.mp4"
    f.write_bytes(b"")
    with pytest.raises(ValueError, match="arquivo"):
        settings.validate_library_dir(str(f))


# ── Transição ───────────────────────────────────────────────────────────────

def test_transition_padrao_corte_seco():
    assert settings.get_transition() == {"type": "cut", "duration": 0.5}


def test_transition_set_parcial_e_persistencia():
    assert settings.set_transition({"type": "fade"}) == {"type": "fade", "duration": 0.5}
    assert settings.set_transition({"duration": 1.25}) == {"type": "fade", "duration": 1.25}
    assert settings.get_transition() == {"type": "fade", "duration": 1.25}
    raw = json.loads(settings.config_path().read_text(encoding="utf-8"))
    assert raw["transition"] == {"type": "fade", "duration": 1.25}


@pytest.mark.parametrize("cfg,msg", [
    ({"type": "dissolve"},  "Tipo"),
    ({"duration": 0.05},    "entre"),
    ({"duration": 5},       "entre"),
    ({"duration": "abc"},   "inválida"),
])
def test_transition_rejeita_invalidos(cfg, msg):
    with pytest.raises(ValueError, match=msg):
        settings.set_transition(cfg)
    assert settings.get_transition() == {"type": "cut", "duration": 0.5}


def test_transition_corrompida_no_arquivo_cai_no_padrao():
    settings.save({"transition": {"type": "x", "duration": 99}})
    assert settings.get_transition() == {"type": "cut", "duration": 0.5}
