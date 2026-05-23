/* PlayLine — Log de eventos e status de conexão */

function esc(str) {
  return String(str ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function log(msg, type) {
  const div = document.getElementById("log");
  const ts = new Date().toTimeString().slice(0, 8);
  const entry = document.createElement("div");
  entry.className = `log-entry ev-${type}`;
  entry.innerHTML = `<span class="ts">${ts}</span><span class="ev">${type}</span><span class="msg">${esc(msg)}</span>`;
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
