/* PlayLine — Log de eventos e status de conexão */

function esc(str) {
  return String(str ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

// Mapeia o "type" de cada chamada log(msg, type) para a chave curta traduzida
// em i18n/*.js (eventlabels.*). A mensagem em si (msg) continua em português:
// são centenas de strings soltas pelo código, fora do escopo desta tradução.
const _LOG_LABEL_KEYS = {
  now_playing:            "now_playing",
  paused:                 "paused",
  resumed:                "resumed",
  stopped:                "stopped",
  playlist_end:           "playlist_end",
  mpv_ready:              "player",
  mpv_closed:             "player",
  stream_reconnecting:    "stream",
  stream_reconnect_failed:"stream",
  info:                   "info",
  warn:                   "warn",
  error:                  "error",
};

function log(msg, type) {
  const div = document.getElementById("log");
  const ts = new Date().toTimeString().slice(0, 8);
  const entry = document.createElement("div");
  entry.className = `log-entry ev-${type}`;
  const labelKey = _LOG_LABEL_KEYS[type];
  const label = labelKey ? window.t("eventlabels." + labelKey) : type;
  entry.innerHTML = `<span class="ts">${ts}</span><span class="ev">${label}</span><span class="msg">${esc(msg)}</span>`;
  div.appendChild(entry);
  div.scrollTop = div.scrollHeight;
}

function setConnStatus(status) {
  const dot   = document.getElementById("dot");
  const label = document.getElementById("conn-label");
  dot.className = "dot " + status;
  const key = { connected: "header.connected", connecting: "header.connecting", disconnected: "header.disconnected" }[status];
  label.textContent = key ? window.t(key) : status;
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
