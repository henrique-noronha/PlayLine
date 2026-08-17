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

  function _close() {
    if (_stream) { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
    if (_videoEl) _videoEl.srcObject = null;
    if (_modal)   _modal.style.display = "none";
  }

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

  window.openCapturePreview = async function (path, anchor) {
    const deviceName = path.replace(/^av:\/\/dshow:video=/, "");

    if (!navigator.mediaDevices?.getUserMedia) {
      if (typeof showToast === "function") showToast("Preview não disponível neste browser", "warn");
      return;
    }

    const el = _getOrCreate();
    _labelEl.textContent = deviceName;
    _position(anchor.closest(".schedule-item") || anchor);

    // Para stream anterior antes de abrir novo
    if (_stream) { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
    _videoEl.srcObject = null;
    el.style.display = "block";

    try {
      // Tenta encontrar o dispositivo pelo nome via enumerateDevices
      // (labels só ficam disponíveis após a primeira permissão concedida)
      const devices  = await navigator.mediaDevices.enumerateDevices();
      const videoDevs = devices.filter(d => d.kind === "videoinput" && d.label);
      const match = videoDevs.find(d =>
        d.label.toLowerCase().includes(deviceName.toLowerCase()) ||
        deviceName.toLowerCase().includes(d.label.toLowerCase())
      );

      const constraints = match
        ? { video: { deviceId: { exact: match.deviceId } } }
        : { video: true };

      _stream = await navigator.mediaDevices.getUserMedia(constraints);
      _videoEl.srcObject = _stream;
    } catch (_e) {
      el.style.display = "none";
      _stream = null;
      if (typeof showToast === "function") showToast("Não foi possível acessar: " + deviceName, "warn");
    }
  };
})();
