/* PlayLine — Preview de live do YouTube */

(function () {
  const modal    = document.getElementById("yt-preview-modal");
  const iframe   = document.getElementById("yt-preview-iframe");
  const btnClose = document.getElementById("yt-preview-close");
  const btnMute  = document.getElementById("yt-preview-mute");

  let _currentUrl = "";
  let _muted = true;

  function _extractId(url) {
    const m = url.match(/[?&]v=([A-Za-z0-9_-]{11})|youtu\.be\/([A-Za-z0-9_-]{11})|youtube\.com\/live\/([A-Za-z0-9_-]{11})/);
    return m ? (m[1] || m[2] || m[3]) : null;
  }

  function _buildSrc(id, forceMuted) {
    const muted = forceMuted !== undefined ? forceMuted : _muted;
    return "https://www.youtube.com/embed/" + id + "?autoplay=1" + (muted ? "&mute=1" : "");
  }

  function _position(anchor) {
    const rect = anchor.getBoundingClientRect();
    const mw = 360, mh = 226;

    let top  = rect.top - mh - 6;
    let left = rect.right - mw;

    if (top < 8)                           top  = rect.bottom + 6;
    if (left < 8)                          left = 8;
    if (left + mw > window.innerWidth - 8) left = window.innerWidth - mw - 8;

    modal.style.top  = top  + "px";
    modal.style.left = left + "px";
  }

  const _SVG_YT_SPEAKER = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';
  const _SVG_YT_MUTED   = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>';

  function _updateMuteBtn() {
    btnMute.innerHTML = _muted ? _SVG_YT_MUTED : _SVG_YT_SPEAKER;
    btnMute.title     = _muted ? "Ativar áudio" : "Silenciar";
  }

  function _close() {
    modal.style.display = "none";
    iframe.src = "";
    _muted = true;
    _updateMuteBtn();
  }

  window.openYtPreview = function (url, anchor) {
    const id = _extractId(url);
    if (!id) return;
    _currentUrl = id;
    _muted = true;
    _updateMuteBtn();
    iframe.src = _buildSrc(id);
    const row = anchor.closest(".schedule-item") || anchor;
    _position(row);
    modal.style.display = "block";
  };

  btnMute.addEventListener("click", e => {
    e.stopPropagation();
    _muted = !_muted;
    _updateMuteBtn();
    if (_currentUrl) iframe.src = _buildSrc(_currentUrl);
  });

  btnClose.addEventListener("click", _close);

  document.addEventListener("click", e => {
    if (modal.style.display !== "none" && !modal.contains(e.target)) _close();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") _close();
  });

  // Exposto pro quadrante fixo de entrada (input_quadrant.js) reaproveitar sem duplicar a regex
  window._ytExtractId     = _extractId;
  window._ytBuildEmbedSrc = _buildSrc;
})();
