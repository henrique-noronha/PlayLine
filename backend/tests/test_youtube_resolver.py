"""Testes para core/youtube_resolver.py.

Cobre a detecção de URL do YouTube (lógica pura) e a resolução via yt-dlp
com a rede mockada (sem bater no YouTube de verdade, sem depender de conexão),
incluindo o retry em falha transitória.
"""
from unittest.mock import MagicMock, patch

import pytest

import core.youtube_resolver as yr


# ── is_youtube_url ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url, esperado", [
    ("https://www.youtube.com/watch?v=abcDEFghijk", True),
    ("https://youtu.be/abcDEFghijk", True),
    ("https://www.youtube.com/live/abcDEFghijk", True),
    ("youtube.com/watch?v=abcDEFghijk", True),
    ("https://vimeo.com/12345", False),
    ("C:\\video.mp4", False),
    ("", False),
])
def test_is_youtube_url(url, esperado):
    assert yr.is_youtube_url(url) == esperado


# ── get_stream_url (via yt-dlp) ──────────────────────────────────────────

def _mock_ydl(mock_yt_dlp, **extract_info_kwargs):
    mock_ydl = MagicMock()
    mock_ydl.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.return_value = extract_info_kwargs
    mock_yt_dlp.YoutubeDL.return_value = mock_ydl
    return mock_ydl


def test_resolve_via_client_android_quando_ja_muxado():
    """O client "android" ainda serve HLS com vídeo+áudio já combinados --
    é a via rápida: o MPV abre um único stream, sem precisar enumerar as
    variantes do manifesto mestre (o que sozinho custava 10s+ por troca de
    live). Deve ser tentado primeiro e, quando funciona, nem chega a cair
    pro client padrão."""
    with patch.object(yr, "_yt_dlp") as mock_yt_dlp:
        _mock_ydl(mock_yt_dlp, formats=[
            {"format_id": "301", "vcodec": "avc1.64002A", "acodec": "mp4a.40.2",
             "height": 1080, "url": "https://googlevideo.com/videoplayback?itag=301"},
            {"format_id": "93", "vcodec": "avc1.4D401E", "acodec": "mp4a.40.2",
             "height": 360, "url": "https://googlevideo.com/videoplayback?itag=93"},
        ])
        resultado = yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")

    assert resultado == "https://googlevideo.com/videoplayback?itag=301"
    mock_yt_dlp.YoutubeDL.assert_called_once()
    opts_usadas = mock_yt_dlp.YoutubeDL.call_args[0][0]
    assert opts_usadas["extractor_args"]["youtube"]["player_client"] == yr._ANDROID_CLIENT


def test_cai_pro_client_padrao_quando_android_falha():
    """O client "android" é um alvo comum das restrições do YouTube -- se
    ele falhar, cai pro client padrão (manifesto HLS mestre) sem retentar
    o android (falha estrutural, não adianta insistir no mesmo client)."""
    with patch.object(yr, "_yt_dlp") as mock_yt_dlp, patch("core.youtube_resolver.time.sleep"):
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = [
            Exception("The page needs to be reloaded."),
            {"formats": [{"manifest_url": "https://manifest.googlevideo.com/master.m3u8"}]},
        ]
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl

        resultado = yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")

    assert resultado == "https://manifest.googlevideo.com/master.m3u8"
    assert mock_ydl.extract_info.call_count == 2
    call_opts = [c[0][0] for c in mock_yt_dlp.YoutubeDL.call_args_list]
    assert call_opts[0]["extractor_args"]["youtube"]["player_client"] == yr._ANDROID_CLIENT
    assert "extractor_args" not in call_opts[1]


def test_usa_url_direta_quando_sem_manifest_url():
    with patch.object(yr, "_yt_dlp") as mock_yt_dlp, patch("core.youtube_resolver.time.sleep"):
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = [
            Exception("android indisponível"),
            {"url": "https://manifest.googlevideo.com/fake.m3u8", "formats": []},
        ]
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl

        resultado = yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")

    assert resultado == "https://manifest.googlevideo.com/fake.m3u8"


def test_usa_requested_formats_quando_sem_manifest_nem_url_direta():
    """Último recurso: nenhum formato HLS disponível — usa a URL do primeiro
    formato (vídeo-only, sem áudio, mas melhor que travar)."""
    with patch.object(yr, "_yt_dlp") as mock_yt_dlp, patch("core.youtube_resolver.time.sleep"):
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = [
            Exception("android indisponível"),
            {"requested_formats": [{"url": "https://manifest.googlevideo.com/fmt0.mp4"}]},
        ]
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl

        resultado = yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")

    assert resultado == "https://manifest.googlevideo.com/fmt0.mp4"


def test_retenta_apos_falha_transitoria_e_resolve():
    """Client android falha (cai pro padrão) -- primeira tentativa do client
    padrão falha (ex.: hiccup de rede), segunda resolve. Não pode precisar
    escalar pro ciclo caro de reconexão do daemon por isso."""
    with patch.object(yr, "_yt_dlp") as mock_yt_dlp, patch("core.youtube_resolver.time.sleep") as mock_sleep:
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = [
            Exception("android indisponível"),
            OSError("falha transitória de rede"),
            {"url": "https://manifest.googlevideo.com/fake.m3u8", "formats": []},
        ]
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl

        resultado = yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")

    assert resultado == "https://manifest.googlevideo.com/fake.m3u8"
    assert mock_ydl.extract_info.call_count == 3
    mock_sleep.assert_called_once_with(yr._YTDLP_RETRY_SEC)


def test_ytdlp_falha_em_tudo_propaga_erro():
    """Se android e as duas tentativas do client padrão falharem, o erro
    deve subir (não pode fingir sucesso nem travar em silêncio)."""
    with patch.object(yr, "_yt_dlp") as mock_yt_dlp, patch("core.youtube_resolver.time.sleep"):
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = OSError("sem rede")
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl

        with pytest.raises(OSError):
            yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")

    # 1 tentativa (android, sem retry) + _YTDLP_ATTEMPTS tentativas (client padrão)
    assert mock_ydl.extract_info.call_count == 1 + yr._YTDLP_ATTEMPTS


def test_sem_url_nem_formatos_propaga_erro():
    with patch.object(yr, "_yt_dlp") as mock_yt_dlp, patch("core.youtube_resolver.time.sleep"):
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = [
            Exception("android indisponível"),
            {},  # sem "url", "formats" nem "requested_formats"
            {},
        ]
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl

        with pytest.raises(RuntimeError):
            yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")
