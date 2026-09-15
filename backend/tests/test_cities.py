"""Testes da lista de cidades do overlay de hora/temperatura (core/settings.py)."""

import json

import pytest

from core import settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PLAYLINE_CONFIG", raising=False)


PALMAS = {"name": "Palmas", "state": "TO", "lat": -10.1838, "lon": -48.3336}
GURUPI = {"name": "Gurupi", "state": "TO", "lat": -11.7279, "lon": -49.068}


# ── padrão ──────────────────────────────────────────────────────────────────

# A lista padrão é definida no código e muda por instalação (a develop traz as
# capitais; uma emissora pode compilar com as cidades da região dela), então os
# testes comparam com default_cities() em vez de fixar a quantidade.
PADRAO = len(settings.default_cities())


def test_sem_arquivo_vale_a_lista_padrao():
    c = settings.get_cities()
    assert c == settings.default_cities()
    assert 0 < len(c) <= settings.CITIES_MAX
    assert all({"name", "state", "lat", "lon"} <= set(x) for x in c)
    assert any(x["name"] == "Palmas" and x["state"] == "TO" for x in c)


def test_limite_maximo_e_30():
    assert settings.CITIES_MAX == 30


# ── gravação ────────────────────────────────────────────────────────────────

def test_set_e_get_round_trip():
    assert settings.set_cities([PALMAS, GURUPI]) == [PALMAS, GURUPI]
    assert settings.get_cities() == [PALMAS, GURUPI]
    raw = json.loads(settings.config_path().read_text(encoding="utf-8"))
    assert len(raw["cities"]) == 2


def test_remove_duplicatas_preservando_ordem():
    dup = dict(PALMAS, name="palmas")          # mesma cidade, caixa diferente
    assert settings.set_cities([PALMAS, GURUPI, dup]) == [PALMAS, GURUPI]


def test_ordem_preservada():
    assert [c["name"] for c in settings.set_cities([GURUPI, PALMAS])] == ["Gurupi", "Palmas"]


def test_aceita_exatamente_30():
    trinta = [dict(PALMAS, name=f"Cidade {i}") for i in range(30)]
    assert len(settings.set_cities(trinta)) == 30


def test_rejeita_mais_de_30():
    with pytest.raises(ValueError, match="limite"):
        settings.set_cities([dict(PALMAS, name=f"Cidade {i}") for i in range(31)])
    assert len(settings.get_cities()) == PADRAO   # padrão intacto


def test_rejeita_lista_vazia_ou_invalida():
    for valor in ([], "Palmas", None, 42):
        with pytest.raises(ValueError):
            settings.set_cities(valor)


@pytest.mark.parametrize("cidade,msg", [
    ({"name": "", "state": "TO", "lat": 0, "lon": 0},              "sem nome"),
    ({"name": "x" * 65, "state": "TO", "lat": 0, "lon": 0},        "muito longo"),
    ({"name": "Palmas", "state": "TOC", "lat": 0, "lon": 0},       "Estado"),
    ({"name": "Palmas", "state": "TO"},                            "Coordenadas"),
    ({"name": "Palmas", "state": "TO", "lat": "x", "lon": 0},      "Coordenadas"),
    ({"name": "Palmas", "state": "TO", "lat": 100, "lon": 0},      "fora de faixa"),
    ("Palmas,TO",                                                  "formato inválido"),
])
def test_rejeita_cidade_invalida(cidade, msg):
    with pytest.raises(ValueError, match=msg):
        settings.set_cities([cidade])


def test_estado_opcional_e_normalizado():
    c = settings.set_cities([{"name": "Palmas", "state": "to", "lat": 1, "lon": 2},
                             {"name": "Somewhere", "lat": 3, "lon": 4}])
    assert c[0]["state"] == "TO"
    assert c[1]["state"] == ""


def test_reset_volta_ao_padrao():
    settings.set_cities([PALMAS])
    assert len(settings.get_cities()) == 1
    assert len(settings.reset_cities()) == PADRAO
    assert len(settings.get_cities()) == PADRAO
    assert "cities" not in json.loads(settings.config_path().read_text(encoding="utf-8"))


def test_entrada_corrompida_no_arquivo_e_ignorada():
    settings.save({"cities": [PALMAS, {"name": "Quebrada"}, "lixo"]})
    assert settings.get_cities() == [PALMAS]


def test_lista_toda_corrompida_cai_no_padrao():
    settings.save({"cities": ["lixo", 42]})
    assert len(settings.get_cities()) == PADRAO


def test_cidades_nao_apagam_outras_configuracoes(tmp_path):
    settings.set_credentials("op", "senha1")
    settings.set_transition({"type": "fade"})
    settings.set_cities([PALMAS])
    assert settings.verify_credentials("op", "senha1")
    assert settings.get_transition()["type"] == "fade"
    assert settings.get_cities() == [PALMAS]


# ── resolução de coordenadas ────────────────────────────────────────────────

def test_find_city_por_nome_e_estado():
    settings.set_cities([PALMAS, GURUPI])
    assert settings.find_city("Palmas,TO") == PALMAS
    assert settings.find_city("palmas,to") == PALMAS
    assert settings.find_city("Palmas") == PALMAS          # sem a sigla
    assert settings.find_city({"name": "Gurupi", "state": "TO"}) == GURUPI


def test_find_city_inexistente_retorna_none():
    settings.set_cities([PALMAS])
    assert settings.find_city("Gurupi,TO") is None
    assert settings.find_city("") is None
    assert settings.find_city(None) is None


def test_find_city_desempata_pelo_estado():
    """Há cinco 'Palmas' no Brasil: a sigla decide qual coordenada vale."""
    palmas_pr = {"name": "Palmas", "state": "PR", "lat": -26.4839, "lon": -51.9888}
    settings.set_cities([PALMAS, palmas_pr])
    assert settings.find_city("Palmas,PR") == palmas_pr
    assert settings.find_city("Palmas,TO") == PALMAS
