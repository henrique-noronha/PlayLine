/* PlayLine — Player de vídeo HTML5 */

const video = document.getElementById("player-video");
let _lastMpvPos = null;
let _syncPending = false;
let _lastSyncAt  = 0;      // performance.now() do último seek de sincronização
let _ytVideoDuration = 0;  // duração manual para vídeos YouTube (MPV não expõe via HTML5)

function fmt(secs) {
  if (secs == null || isNaN(secs)) return "00:00:00";
  secs = Math.floor(secs);
  const h = String(Math.floor(secs / 3600)).padStart(2, "0");
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, "0");
  const s = String(secs % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function fmtTime(date) {
  if (!date) return "--:--";
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function _showUnavailable() {
  let el = document.getElementById("preview-unavailable");
  if (!el) {
    el = document.createElement("div");
    el.id = "preview-unavailable";
    el.textContent = "Preview não disponível para este formato";
    video.parentNode.appendChild(el);
  }
  el.style.display = "flex";
}

function _hideUnavailable() {
  const el = document.getElementById("preview-unavailable");
  if (el) el.style.display = "none";
}

// Modo YouTube: usa eventos de posição do MPV para atualizar a barra de progresso,
// já que o browser não consegue carregar a URL do YouTube diretamente.
function setYtVideoMode(duration) {
  _ytVideoDuration = duration || 0;
  video.removeAttribute("src");
  video.load();
  resetProgress();
}

// startAt > 1: appends #t=N so the browser opens the file at that second natively,
// avoiding a post-load manual seek (which freezes while buffering).
function loadVideo(path, startAt = 0) {
  _ytVideoDuration = 0;
  _lastMpvPos = startAt > 1 ? startAt : null;
  _syncPending = false;
  _lastSyncAt  = 0;
  _hideUnavailable();
  _restoreLogoOverlays();
  const fragment = startAt > 1 ? `#t=${Math.floor(startAt)}` : '';
  const url = "/media?path=" + encodeURIComponent(path) + fragment;
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
  _ytVideoDuration = 0;
  _lastMpvPos = null;
  _hideUnavailable();
  video.removeAttribute("src");
  video.load();
  resetProgress();
  hideLiveIndicator();
  document.querySelectorAll(".logo-overlay").forEach(el => el.style.display = "none");
}

function showLiveIndicator() {
  _ytVideoDuration = 0;
  // Limpa o elemento <video> para impedir que syncPosition atualize a barra
  video.removeAttribute("src");
  video.load();
  resetProgress();
  document.getElementById("progress-wrap").style.display = "none";
  document.getElementById("live-indicator").style.display = "flex";
}

function hideLiveIndicator() {
  document.getElementById("progress-wrap").style.display = "";
  document.getElementById("live-indicator").style.display = "none";
}

// Threshold alto: drift normal de playback (1-2s de buffering) nunca dispara resync.
// Só corrige saltos reais (próximo clipe, seek manual, reconexão com grande offset).
const _SYNC_THRESHOLD_S  = 12;   // segundos de diferença para forçar resync
const _SYNC_COOLDOWN_MS  = 6000; // ms mínimos entre dois resyncs consecutivos

function syncPosition(pos) {
  _lastMpvPos = pos;
  // Modo YouTube: atualiza barra diretamente via posição do MPV
  if (_ytVideoDuration > 0) {
    document.getElementById("pos").textContent = fmt(pos);
    document.getElementById("dur").textContent = fmt(_ytVideoDuration);
    const pct = Math.min((pos / _ytVideoDuration) * 100, 100);
    document.getElementById("progress-fill").style.width = pct + "%";
    return;
  }
  if (!video.src || isNaN(video.duration) || video.duration === 0) return;
  if (_syncPending) return;
  if (performance.now() - _lastSyncAt < _SYNC_COOLDOWN_MS) return;
  if (Math.abs(video.currentTime - pos) > _SYNC_THRESHOLD_S) {
    _syncPending = true;
    _lastSyncAt  = performance.now();
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
  // Sem seek manual aqui: quando loadVideo usa #t=N, o browser já inicia
  // na posição certa via range request nativo, sem freeze de buffering.
});

video.addEventListener("seeked", () => {
  _syncPending = false;
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
  // Só mostra mensagem se o canvas MPV não estiver recebendo frames
  const wrap = video.closest(".player-wrap");
  if (!wrap?.classList.contains("mpv-live")) {
    _showUnavailable();
  }
});
