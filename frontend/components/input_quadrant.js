/* PlayLine — Quadrante fixo de entrada (Câmera / YouTube) ao lado do Roteiro.

   Reaproveita o que já existe: getUserMedia (capture_preview.js) e o embed
   do YouTube (yt_preview.js) pra manter um preview persistente aqui, e os
   modais de sempre (capture.js/youtube_live.js) pra configurar/adicionar. */
(function () {
  const btnCamera  = document.getElementById("iq-btn-camera");
  const btnYoutube = document.getElementById("iq-btn-youtube");
  const btnAdd     = document.getElementById("iq-btn-add");
  const video      = document.getElementById("iq-preview-video");
  const iframe     = document.getElementById("iq-preview-iframe");
  const emptyEl    = document.getElementById("iq-preview-empty");

  if (!btnCamera || !btnYoutube) return;

  let _mode   = null; // "camera" | "youtube" | null
  let _stream = null;

  function _findItem(type) {
    return (state.schedule || []).find(it => it.type === type);
  }

  // Ver isCaptureDeviceNeededSoon() em app.js — mesma checagem (atual ou
  // próximo da fila) usada por todo preview de captura no navegador, pra não
  // disputar o dispositivo com o MPV.
  function _needsToStayFree(item) {
    return !!window.isCaptureDeviceNeededSoon?.(item.path);
  }

  function _clearPreview() {
    if (_stream) { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
    video.srcObject   = null;
    video.style.display  = "none";
    iframe.src        = "";
    iframe.style.display = "none";
  }

  function _showEmpty(msg) {
    emptyEl.textContent  = msg;
    emptyEl.style.display = "";
  }

  async function _showCamera(item) {
    _clearPreview();
    const deviceName = item.path.replace(/^av:\/\/dshow:video=/, "");
    if (_needsToStayFree(item)) {
      // Não abre o mesmo dispositivo aqui — deixa exclusivo pro MPV, que é
      // quem realmente está transmitindo (ou está prestes a). Ver "Reproduzindo
      // agora" pro preview real.
      _showEmpty("Ao vivo agora (ou é a próxima da fila) — sem preview duplicado para não travar a transmissão");
      return;
    }
    if (typeof window._captureGetStream !== "function") return;
    _stream = await window._captureGetStream(deviceName);
    if (_stream) {
      video.srcObject     = _stream;
      video.muted          = true; // nunca deixa o preview vazar áudio por cima da transmissão real
      video.style.display = "block";
      emptyEl.style.display = "none";
    } else {
      _showEmpty("Não foi possível acessar: " + deviceName);
    }
  }

  function _showYoutube(item) {
    _clearPreview();
    if (typeof window._ytExtractId !== "function" || typeof window._ytBuildEmbedSrc !== "function") return;
    const id = window._ytExtractId(item.path);
    if (!id) { _showEmpty("Link do YouTube inválido"); return; }
    // força mudo sempre — o preview não pode disputar áudio com a transmissão real
    iframe.src           = window._ytBuildEmbedSrc(id, true);
    iframe.style.display = "block";
    emptyEl.style.display = "none";
  }

  function _updateToggleUI() {
    btnCamera.classList.toggle("active", _mode === "camera");
    btnYoutube.classList.toggle("active", _mode === "youtube");
    if (btnAdd) {
      btnAdd.textContent = _mode === "youtube"
        ? "+ Adicionar outra live"
        : "+ Adicionar outra câmera";
    }
  }

  function _openAddModal(type) {
    if (type === "camera" && typeof window.openCaptureModal === "function") window.openCaptureModal();
    if (type === "youtube" && typeof window.openYtModal === "function") window.openYtModal();
  }

  function selectSource(type) {
    const item = _findItem(type === "camera" ? "capture" : "youtube_live");
    if (item) {
      _mode = type;
      _updateToggleUI();
      if (type === "camera") _showCamera(item); else _showYoutube(item);
    } else {
      _openAddModal(type);
    }
  }

  function _refreshActive() {
    if (!_mode) return;
    const item = _findItem(_mode === "camera" ? "capture" : "youtube_live");
    if (!item) {
      _mode = null;
      _clearPreview();
      _showEmpty("Nenhuma entrada ativa");
      _updateToggleUI();
      return;
    }
    if (_mode === "camera") _showCamera(item); else _showYoutube(item);
  }

  btnCamera.addEventListener("click", () => selectSource("camera"));
  btnYoutube.addEventListener("click", () => selectSource("youtube"));
  if (btnAdd) btnAdd.addEventListener("click", () => _openAddModal(_mode || "camera"));

  // Chamado por playlist.js ao fim de renderSchedule() — cobre tanto item
  // adicionado agora (modal) quanto removido/alterado via schedule_updated.
  window._onScheduleChangedForInputQuadrant = function () {
    if (!_mode) {
      // Primeira entrada de um tipo aparecendo: já mostra o preview automaticamente
      const captureItem = _findItem("capture");
      const ytItem       = _findItem("youtube_live");
      if (captureItem && !ytItem)      { _mode = "camera";  _updateToggleUI(); _showCamera(captureItem); }
      else if (ytItem && !captureItem) { _mode = "youtube"; _updateToggleUI(); _showYoutube(ytItem); }
      return;
    }
    _refreshActive();
  };

  _updateToggleUI();
  _showEmpty("Nenhuma entrada ativa");
})();
