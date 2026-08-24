"""Testes para core/youtube_resolver.py.

Cobre a detecção/extração de URL do YouTube (lógica pura) e o fallback
InnerTube -> yt-dlp com a rede mockada (sem bater no YouTube de verdade,
sem depender de conexão). O cenário de fallback reproduz o que foi observado
em produção: o InnerTube volta a quebrar periodicamente (o YouTube descontinua
as versões de cliente que o código finge ser) e o sistema precisa continuar
resolvendo lives via yt-dlp mesmo assim.
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


# ── _extract_video_id ────────────────────────────────────────────────────

@pytest.mark.parametrize("url, esperado", [
    ("https://www.youtube.com/watch?v=abcDEFghijk", "abcDEFghijk"),
    ("https://youtu.be/abcDEFghijk", "abcDEFghijk"),
    ("https://www.youtube.com/live/abcDEFghijk", "abcDEFghijk"),
    ("https://vimeo.com/12345", None),
])
def test_extract_video_id(url, esperado):
    assert yr._extract_video_id(url) == esperado


# ── Fallback InnerTube -> yt-dlp ─────────────────────────────────────────

def test_fallback_para_ytdlp_quando_innertube_falha():
    """Os dois clientes do InnerTube (ANDROID e IOS) falham -- precisa cair
    pro yt-dlp e ainda assim resolver a URL, igual acontece em produção hoje."""
    with patch(
        "core.youtube_resolver.urllib.request.urlopen",
        side_effect=OSError("HTTP Error 400: Bad Request"),
    ) as mock_urlopen, patch.object(yr, "_yt_dlp") as mock_yt_dlp:
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "url": "https://manifest.googlevideo.com/fake.m3u8",
            "protocol": "m3u8_native",
        }
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl

        resultado = yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")

    assert resultado == "https://manifest.googlevideo.com/fake.m3u8"
    assert mock_urlopen.call_count == 2  # tentou ANDROID e IOS antes de desistir


def test_usa_innertube_quando_disponivel_sem_cair_no_ytdlp():
    """Caminho feliz: se o InnerTube responder OK, o yt-dlp nem deveria ser chamado."""
    resposta_ok = MagicMock()
    resposta_ok.__enter__.return_value = resposta_ok
    resposta_ok.read.return_value = (
        b'{"playabilityStatus": {"status": "OK"}, '
        b'"streamingData": {"hlsManifestUrl": "https://manifest.googlevideo.com/rapido.m3u8"}}'
    )

    with patch(
        "core.youtube_resolver.urllib.request.urlopen", return_value=resposta_ok
    ), patch.object(yr, "_yt_dlp") as mock_yt_dlp:
        resultado = yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")

    assert resultado == "https://manifest.googlevideo.com/rapido.m3u8"
    mock_yt_dlp.YoutubeDL.assert_not_called()


def test_innertube_e_ytdlp_falham_propaga_erro():
    """Se nem o InnerTube nem o yt-dlp resolverem, o erro deve subir (não
    deve fingir sucesso nem travar em silêncio)."""
    with patch(
        "core.youtube_resolver.urllib.request.urlopen",
        side_effect=OSError("sem rede"),
    ), patch.object(yr, "_yt_dlp") as mock_yt_dlp:
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {}  # sem "url" nem "requested_formats"
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl

        with pytest.raises(RuntimeError):
            yr.get_stream_url("https://www.youtube.com/watch?v=abcDEFghijk")
