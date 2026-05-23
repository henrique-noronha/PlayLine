/* PlayLine — Player de vídeo HTML5 */

const video = document.getElementById("player-video");

function fmt(secs) {
  if (secs == null || isNaN(secs)) return "0:00";
  secs = Math.floor(secs);
  const m = Math.floor(secs / 60);
  const s = String(secs % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function fmtTime(date) {
  if (!date) return "--:--";
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function loadVideo(path) {
  const url = "/media?path=" + encodeURIComponent(path);
  log(`Carregando: ${url}`, "info");
  video.src = url;
  video.load();
  video.play().catch(e => log(`Autoplay: ${e.message}`, "info"));
}

function stopVideo() {
  video.pause();
  video.removeAttribute("src");
  video.load();
  resetProgress();
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
  log("Vídeo finalizado — avançando", "info");
  send({ action: "next" });
});

video.addEventListener("error", () => {
  const code = video.error ? video.error.code : "?";
  log(`Erro no vídeo (código ${code}) — avançando`, "error");
  send({ action: "next" });
});
