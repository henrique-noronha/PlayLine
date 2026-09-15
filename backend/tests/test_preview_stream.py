"""Testes para daemon/preview_stream.py -- o separador de frames JPEG do
stream MJPEG cru que o ffmpeg (ddagrab) manda pelo stdout.

É lógica pura (dados bytes chegando aos poucos -> lista de frames completos),
testável sem precisar de GPU, monitor secundário nem processo ffmpeg de verdade.
"""
from daemon.preview_stream import _JpegFrameSplitter


def test_frame_completo_em_um_unico_chunk():
    s = _JpegFrameSplitter()
    frame = b"\xff\xd8" + b"dadosdaimagem" + b"\xff\xd9"
    assert s.feed(frame) == [frame]


def test_frame_dividido_em_varios_chunks():
    s = _JpegFrameSplitter()
    frame = b"\xff\xd8" + b"dadosdaimagem" + b"\xff\xd9"
    meio = len(frame) // 2
    assert s.feed(frame[:meio]) == []       # ainda incompleto -- nenhum frame ainda
    assert s.feed(frame[meio:]) == [frame]  # completou com o resto


def test_multiplos_frames_no_mesmo_chunk():
    f1 = b"\xff\xd8AAA\xff\xd9"
    f2 = b"\xff\xd8BBB\xff\xd9"
    s = _JpegFrameSplitter()
    assert s.feed(f1 + f2) == [f1, f2]


def test_lixo_antes_do_primeiro_frame_e_descartado():
    s = _JpegFrameSplitter()
    frame = b"\xff\xd8XYZ\xff\xd9"
    assert s.feed(b"lixo qualquer antes" + frame) == [frame]


def test_stream_continuo_entre_varias_chamadas_de_feed():
    """Simula vários frames chegando ao longo do tempo, como no stream real."""
    s = _JpegFrameSplitter()
    frames_esperados = [b"\xff\xd8" + bytes([i]) * 5 + b"\xff\xd9" for i in range(5)]

    coletados = []
    for frame in frames_esperados:
        coletados.extend(s.feed(frame))

    assert coletados == frames_esperados


def test_sem_marcador_de_inicio_buffer_fica_vazio():
    s = _JpegFrameSplitter()
    assert s.feed(b"nada de jpeg aqui") == []
    # próximo feed não deve carregar lixo acumulado indefinidamente
    frame = b"\xff\xd8OK\xff\xd9"
    assert s.feed(frame) == [frame]
