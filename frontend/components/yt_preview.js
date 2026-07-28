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

  function _buildSrc(id) {
    return "https://www.youtube.com/embed/" + id + "?autoplay=1" + (_muted ? "&mute=1" : "");
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

  function _updateMuteBtn() {
    btnMute.textContent = _muted ? "🔇" : "🔊";
    btnMute.title       = _muted ? "Ativar áudio" : "Silenciar";
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
})();
