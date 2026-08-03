/* PlayLine — Log de eventos e status de conexão */

function esc(str) {
  return String(str ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

const _LOG_LABELS = {
  now_playing:            "reprodução",
  paused:                 "pausa",
  resumed:                "retomada",
  stopped:                "parado",
  playlist_end:           "roteiro",
  mpv_ready:              "player",
  mpv_closed:             "player",
  stream_reconnecting:    "stream",
  stream_reconnect_failed:"stream",
  info:                   "info",
  warn:                   "aviso",
  error:                  "erro",
};

function log(msg, type) {
  const div = document.getElementById("log");
  const ts = new Date().toTimeString().slice(0, 8);
  const entry = document.createElement("div");
  entry.className = `log-entry ev-${type}`;
  const label = _LOG_LABELS[type] ?? type;
  entry.innerHTML = `<span class="ts">${ts}</span><span class="ev">${label}</span><span class="msg">${esc(msg)}</span>`;
  div.appendChild(entry);
  div.scrollTop = div.scrollHeight;
}

function setConnStatus(status) {
  const dot   = document.getElementById("dot");
  const label = document.getElementById("conn-label");
  dot.className = "dot " + status;
  label.textContent = { connected: "Conectado", connecting: "Conectando…", disconnected: "Desconectado" }[status] ?? status;
}

document.getElementById("btn-clear-log").addEventListener("click", () => {
  document.getElementById("log").innerHTML = "";
});

function showToast(msg, type = "warn") {
  const el = document.createElement("div");
  el.className = `pl-toast pl-toast-${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("pl-toast-visible"));
  setTimeout(() => {
    el.classList.remove("pl-toast-visible");
    el.addEventListener("transitionend", () => el.remove(), { once: true });
  }, 4000);
}
