"""Captura contínua do monitor secundário via ffmpeg (Desktop Duplication API / ddagrab)."""
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import AsyncIterator, Optional

logger = logging.getLogger("mpv_daemon")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_W, _H = 720, 405   # 16:9, mesma resolução alvo do preview via MPV
_FPS   = 10
_Q     = "5"        # qualidade MJPEG do ffmpeg (2=melhor, 31=pior)

_OUTPUT_IDX = int(os.environ.get("PLAYLINE_DDAGRAB_OUTPUT", "1"))


def _ffmpeg_path() -> Path:
    if getattr(sys, "frozen", False):
        # PlayLine-daemon.exe é um onefile à parte do PlayLine.exe (onedir) — o
        # ffmpeg.exe embutido termina em "_internal/" ao lado dele, não junto do daemon.
        base = Path(sys.executable).parent
        for candidate in (base / "ffmpeg.exe", base / "_internal" / "ffmpeg.exe"):
            if candidate.exists():
                return candidate
        return base / "ffmpeg.exe"
    return Path(__file__).parent.parent / "ffmpeg.exe"


class _JpegFrameSplitter:
    """Extrai frames JPEG completos de um stream MJPEG cru."""
    _SOI = b"\xff\xd8"
    _EOI = b"\xff\xd9"

    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list:
        """Adiciona bytes recebidos; retorna a lista de frames JPEG completos encontrados."""
        self._buf.extend(chunk)
        frames = []
        while True:
            start = self._buf.find(self._SOI)
            if start == -1:
                self._buf.clear()
                break
            end = self._buf.find(self._EOI, start + 2)
            if end == -1:
                if start > 0:
                    del self._buf[:start]
                break
            end += 2
            frames.append(bytes(self._buf[start:end]))
            del self._buf[:end]
        return frames


class DesktopCapture:
    """Processo ffmpeg persistente capturando um monitor via ddagrab, entregando frames JPEG."""

    def __init__(self, output_idx: int = _OUTPUT_IDX):
        self._output_idx = output_idx
        self._proc: Optional[asyncio.subprocess.Process] = None

    async def start(self) -> bool:
        exe = _ffmpeg_path()
        if not exe.exists():
            logger.warning("[desktop-capture] ffmpeg.exe não encontrado em %s", exe)
            return False

        cmd = [
            str(exe), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"ddagrab=output_idx={self._output_idx}:framerate={_FPS}:draw_mouse=0",
            "-vf", f"hwdownload,format=bgra,scale={_W}:{_H}",
            "-f", "mjpeg", "-q:v", _Q, "-an", "pipe:1",
        ]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:
            logger.warning("[desktop-capture] falha ao iniciar ffmpeg: %s", exc)
            return False

        # Dá tempo do ffmpeg falhar rápido (ex.: output_idx inexistente) antes de assumir sucesso
        await asyncio.sleep(0.3)
        if self._proc.returncode is not None:
            err = b""
            try:
                err = await asyncio.wait_for(self._proc.stderr.read(2000), timeout=0.5)
            except Exception:
                pass
            logger.warning(
                "[desktop-capture] ffmpeg encerrou imediatamente (código %s) — output_idx=%d inválido? %s",
                self._proc.returncode, self._output_idx, err.decode(errors="replace").strip(),
            )
            self._proc = None
            return False

        asyncio.ensure_future(self._drain_stderr())
        logger.info(
            "[desktop-capture] captura iniciada — output_idx=%d %dx%d@%dfps",
            self._output_idx, _W, _H, _FPS,
        )
        return True

    async def _drain_stderr(self):
        if not self._proc or not self._proc.stderr:
            return
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    # ffmpeg roda com -loglevel error, então qualquer linha aqui é
                    # sinal de problema real (ex.: DXGI access-lost) — vale logar
                    # pra não ficarmos cegos na próxima falha em campo.
                    logger.warning("[desktop-capture] ffmpeg: %s", text)
        except Exception:
            pass

    _STALL_TIMEOUT = 6.0  # s sem nenhum byte novo — trata como travado e encerra p/ permitir retry

    async def frames(self) -> AsyncIterator[bytes]:
        """Gera frames JPEG completos do stdout do ffmpeg (com timeout de stall)."""
        if not self._proc or not self._proc.stdout:
            return
        splitter = _JpegFrameSplitter()
        while True:
            try:
                chunk = await asyncio.wait_for(self._proc.stdout.read(65536), timeout=self._STALL_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("[desktop-capture] sem frames há %.0fs — ffmpeg travado, encerrando captura", self._STALL_TIMEOUT)
                break
            if not chunk:
                break
            for frame in splitter.feed(chunk):
                yield frame

    async def stop(self):
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.kill()
                await self._proc.wait()
            except Exception:
                pass
        self._proc = None
