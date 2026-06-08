/* PlayLine — Player de vídeo HTML5 */

const video = document.getElementById("player-video");
let _lastMpvPos = null;

function fmt(secs) {
  if (secs == null || isNaN(secs)) return "0:00";
  secs = Math.floor(secs);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = String(secs % 60).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${s}`;
  return `${m}:${s}`;
}

function fmtTime(date) {
  if (!date) return "--:--";
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function _showUnavailable() {
  let el = document.getElementById("preview-unavailable");
  if (!el) {
    el = document.createElement("div");
    el.id = "preview-unavailable";
    el.textContent = "Preview não disponível para este formato";
    video.parentNode.appendChild(el);
  }
  video.style.display = "none";
  el.style.display = "flex";
}

function _hideUnavailable() {
  const el = document.getElementById("preview-unavailable");
  if (el) el.style.display = "none";
  video.style.display = "block";
}

function loadVideo(path) {
  _lastMpvPos = null;
  _hideUnavailable();
  _restoreLogoOverlays();
  const url = "/media?path=" + encodeURIComponent(path);
  log(`Carregando: ${url}`, "info");
  video.src = url;
  video.play().catch(e => { if (e.name !== "AbortError") log(`Autoplay: ${e.message}`, "warn"); });
}

function _restoreLogoOverlays() {
  if (typeof _logoState === "undefined" || typeof _updateLogoOverlay === "undefined") return;
  [1, 2].forEach(slot => {
    const s = _logoState[slot];
    _updateLogoOverlay(slot, s.corner, s.active);
  });
}

function stopVideo() {
  _lastMpvPos = null;
  _hideUnavailable();
  video.removeAttribute("src");
  video.load();
  resetProgress();
  document.querySelectorAll(".logo-overlay").forEach(el => el.style.display = "none");
}

function syncPosition(pos) {
  _lastMpvPos = pos;
  if (!video.src || isNaN(video.duration) || video.duration === 0) return;
  if (Math.abs(video.currentTime - pos) > 1.5) {
    video.currentTime = pos;
  }
}

function resetProgress() {
  document.getElementById("progress-fill").style.width = "0%";
  document.getElementById("pos").textContent = "0:00";
  document.getElementById("dur").textContent = "0:00";
}

function updateNowPlaying(item) {
  document.getElementById("np-title").textContent = item ? item.title : "—";
  if (!item) resetProgress();
}

function updateBadge(status) {
  const badge = document.getElementById("state-badge");
  badge.className = "state-badge " + (status === "playing" ? "playing" : status === "paused" ? "paused" : "");
  badge.textContent = { playing: "reproduzindo", paused: "pausado", stopped: "parado" }[status] ?? status;
}

video.addEventListener("loadedmetadata", () => {
  log(`Metadados OK — duração: ${fmt(video.duration)}`, "info");
  if (_lastMpvPos !== null && _lastMpvPos > 1.0) {
    video.currentTime = _lastMpvPos;
  }
});

video.addEventListener("timeupdate", () => {
  const pos = video.currentTime || 0;
  const dur = isFinite(video.duration) ? video.duration : 0;
  document.getElementById("pos").textContent = fmt(pos);
  document.getElementById("dur").textContent = fmt(dur);
  const pct = dur > 0 ? Math.min((pos / dur) * 100, 100) : 0;
  document.getElementById("progress-fill").style.width = pct + "%";
});

video.addEventListener("ended", () => {
  log("Preview finalizado", "info");
});

video.addEventListener("error", () => {
  const code = video.error ? video.error.code : "?";
  log(`Erro no preview (código ${code})`, "error");
  _showUnavailable();
});
