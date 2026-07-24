/* PlayLine — Preview de live do YouTube (iframe mudo) */

(function () {
  const modal    = document.getElementById("yt-preview-modal");
  const iframe   = document.getElementById("yt-preview-iframe");
  const btnClose = document.getElementById("yt-preview-close");

  function _extractId(url) {
    const m = url.match(/[?&]v=([A-Za-z0-9_-]{11})|youtu\.be\/([A-Za-z0-9_-]{11})|youtube\.com\/live\/([A-Za-z0-9_-]{11})/);
    return m ? (m[1] || m[2] || m[3]) : null;
  }

  function _position(anchor) {
    const rect = anchor.getBoundingClientRect();
    const mw = 360, mh = 226; // 360x203 iframe + 23px header

    let top  = rect.top - mh - 6;
    let left = rect.right - mw;

    if (top < 8)                        top  = rect.bottom + 6;
    if (left < 8)                       left = 8;
    if (left + mw > window.innerWidth - 8) left = window.innerWidth - mw - 8;

    modal.style.top  = top  + "px";
    modal.style.left = left + "px";
  }

  function _close() {
    modal.style.display = "none";
    iframe.src = "";
  }

  window.openYtPreview = function (url, anchor) {
    const id = _extractId(url);
    if (!id) return;
    const row = anchor.closest(".schedule-item") || anchor;
    iframe.src = "https://www.youtube.com/embed/" + id + "?autoplay=1&mute=1";
    _position(row);
    modal.style.display = "block";
  };

  btnClose.addEventListener("click", _close);

  document.addEventListener("click", e => {
    if (modal.style.display !== "none" && !modal.contains(e.target)) _close();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") _close();
  });
})();
