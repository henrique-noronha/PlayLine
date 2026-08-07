/* PlayLine — preview_ws.js: stream de frames MPV em tempo real via WebSocket */

(function () {
  const RECONNECT_MS = 3000;
  const STALE_MS     = 2500;   // sem frame por este tempo → considera sinal perdido

  const canvas = document.getElementById("mpv-preview");
  const wrap   = canvas?.closest(".player-wrap");
  const ctx    = canvas?.getContext("2d");

  if (!canvas || !ctx) return;

  let _ws         = null;
  let _lastFrame  = 0;
  let _staleTimer = null;
  let _statusMsg  = null;   // mensagem personalizada exibida no lugar de "Aguardando…"
  let _decoding   = false;  // true enquanto um frame está sendo decodificado

  function _drawNoSignal() {
    const W = canvas.width  || 400;
    const H = canvas.height || 225;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "rgba(255,255,255,0.18)";
    ctx.font = "13px 'Segoe UI', Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(_statusMsg || "Aguardando sinal de vídeo…", W / 2, H / 2);
  }

  function _setLive(active) {
    if (!wrap) return;
    const was = wrap.classList.contains("mpv-live");
    wrap.classList.toggle("mpv-live", active);
    if (!active && was) _drawNoSignal();
  }

  // Expõe para app.js definir mensagem de carregamento de live
  window._setPreviewStatus = function (msg) {
    _statusMsg = msg || null;
    _drawNoSignal();
  };

  function _drawFrame(blob) {
    _statusMsg = null;
    _lastFrame = Date.now();
    _setLive(true);

    clearTimeout(_staleTimer);
    _staleTimer = setTimeout(() => {
      if (Date.now() - _lastFrame >= STALE_MS) _setLive(false);
    }, STALE_MS + 150);

    if (_decoding) return; // já decodificando — descarta frame recebido
    _decoding = true;

    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      _decoding = false;
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      _decoding = false;
    };
    img.src = url;
  }

  function connect() {
    if (_ws) { try { _ws.close(); } catch (_) {} _ws = null; }

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    _ws = new WebSocket(`${proto}//${location.host}/ws/preview`);
    _ws.binaryType = "blob";

    _ws.onopen = () => {
      _lastFrame = 0;
      _decoding  = false;
      _setLive(false);
      _drawNoSignal();
    };

    _ws.onmessage = (e) => {
      if (e.data instanceof Blob) _drawFrame(e.data);
    };

    _ws.onclose = () => {
      _setLive(false);
      setTimeout(connect, RECONNECT_MS);
    };

    _ws.onerror = () => { _ws?.close(); };
  }

  // Inicia após DOM estar pronto
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", connect);
  } else {
    connect();
  }
})();
