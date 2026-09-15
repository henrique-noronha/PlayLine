/* PlayLine — Preview ao vivo de dispositivo de captura (DirectShow/webcam) */

(function () {
  let _modal    = null;
  let _videoEl  = null;
  let _labelEl  = null;
  let _stream   = null;

  function _getOrCreate() {
    if (_modal) return _modal;
    _modal   = document.getElementById("capture-preview-modal");
    _videoEl = document.getElementById("capture-preview-video");
    _labelEl = document.getElementById("capture-preview-label");

    document.getElementById("capture-preview-close").addEventListener("click", _close);

    document.addEventListener("click", e => {
      if (_modal.style.display !== "none" && !_modal.contains(e.target)) _close();
    });
    document.addEventListener("keydown", e => { if (e.key === "Escape") _close(); });
    return _modal;
  }

  let _openPath = null;

  function _close() {
    if (_stream) { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
    if (_videoEl) _videoEl.srcObject = null;
    if (_modal)   _modal.style.display = "none";
    _openPath = null;
  }

  // Chamado nas trocas de item (now_playing/stopped/playlist_end, ver app.js)
  // pra soltar o dispositivo caso o popup tenha ficado aberto justamente
  // quando o item dele virou o atual ou o próximo da fila.
  window._captureReleaseIfNeededSoon = function () {
    if (_openPath && window.isCaptureDeviceNeededSoon?.(_openPath)) _close();
  };

  // Chamado via evento "capture_device_releasing" (ver app.js) — o servidor
  // está prestes a mandar o MPV abrir esse dispositivo, solta incondicionalmente
  // (sem checar isCaptureDeviceNeededSoon: já foi decidido, é agora).
  window._captureForceRelease = function (path) {
    if (_openPath === path) _close();
  };

  function _position(anchor) {
    const rect = anchor.getBoundingClientRect();
    const mw = 360, mh = 229;
    let top  = rect.top - mh - 6;
    let left = rect.right - mw;
    if (top < 8)                            top  = rect.bottom + 6;
    if (left < 8)                           left = 8;
    if (left + mw > window.innerWidth - 8)  left = window.innerWidth - mw - 8;
    _modal.style.top  = top  + "px";
    _modal.style.left = left + "px";
  }

  // Encontra o dispositivo pelo nome (labels só ficam disponíveis após a primeira permissão
  // concedida) e retorna o MediaStream, ou null se não conseguir acessar.
  // Exposto pro quadrante fixo de entrada (input_quadrant.js) reaproveitar sem duplicar.
  window._captureGetStream = async function (deviceName) {
    if (!navigator.mediaDevices?.getUserMedia) return null;
    try {
      const devices   = await navigator.mediaDevices.enumerateDevices();
      const videoDevs = devices.filter(d => d.kind === "videoinput" && d.label);
      const match = videoDevs.find(d =>
        d.label.toLowerCase().includes(deviceName.toLowerCase()) ||
        deviceName.toLowerCase().includes(d.label.toLowerCase())
      );
      const constraints = match
        ? { video: { deviceId: { exact: match.deviceId } } }
        : { video: true };
      return await navigator.mediaDevices.getUserMedia(constraints);
    } catch (_e) {
      return null;
    }
  };

  window.openCapturePreview = async function (path, anchor) {
    const deviceName = path.replace(/^av:\/\/dshow:video=/, "");

    if (!navigator.mediaDevices?.getUserMedia) {
      if (typeof showToast === "function") showToast("Preview não disponível neste browser", "warn");
      return;
    }

    // Mesmo dispositivo está no ar (ou prestes a) — não disputa com o MPV.
    // Ver isCaptureDeviceNeededSoon() em app.js.
    if (window.isCaptureDeviceNeededSoon?.(path)) {
      if (typeof showToast === "function") showToast("Ao vivo agora — sem preview duplicado para não travar a transmissão", "warn");
      return;
    }

    const el = _getOrCreate();
    _labelEl.textContent = deviceName;
    _position(anchor.closest(".schedule-item") || anchor);

    // Para stream anterior antes de abrir novo
    if (_stream) { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
    _videoEl.srcObject = null;
    el.style.display = "block";
    _openPath = path;

    _stream = await window._captureGetStream(deviceName);
    if (_stream) {
      _videoEl.srcObject = _stream;
    } else {
      el.style.display = "none";
      _openPath = null;
      if (typeof showToast === "function") showToast("Não foi possível acessar: " + deviceName, "warn");
    }
  };
})();
