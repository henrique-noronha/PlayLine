/* ── Playout TV — app.js ── */

const WS_URL = `ws://${location.host}/ws`;

// ------------------------------------------------------------------ //
// Estado                                                               //
// ------------------------------------------------------------------ //
const state = {
  ws: null,
  connected: false,
  schedule: [],
  currentIndex: -1,
  playing: false,
  paused: false,
  posTimer: null,
};

// ------------------------------------------------------------------ //
// WebSocket                                                            //
// ------------------------------------------------------------------ //
function connect() {
  setConnStatus("connecting");
  state.ws = new WebSocket(WS_URL);

  state.ws.onopen = () => {
    state.connected = true;
    setConnStatus("connected");
    log("conectado", "info");
  };

  state.ws.onclose = () => {
    state.connected = false;
    setConnStatus("disconnected");
    log("conexão encerrada — reconectando em 3s…", "error");
    setTimeout(connect, 3000);
  };

  state.ws.onerror = () => log("erro de WebSocket", "error");

  state.ws.onmessage = (e) => {
    try {
      handleEvent(JSON.parse(e.data));
    } catch (err) {
      log(`parse error: ${err.message}`, "error");
    }
  };
}

function send(cmd) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(cmd));
  }
}

// ------------------------------------------------------------------ //
// Eventos vindos do servidor                                           //
// ------------------------------------------------------------------ //
function handleEvent(ev) {
  const type = ev.event ?? "state";
  log(JSON.stringify(ev), type);

  switch (type) {
    case "state":
      applyState(ev);
      break;
    case "now_playing":
      state.currentIndex = ev.index;
      state.playing = true;
      state.paused = false;
      updateNowPlaying(ev.item);
      updateBadge("playing");
      highlightActive(ev.index);
      break;
    case "paused":
      state.paused = true;
      updateBadge("paused");
      document.getElementById("btn-play").textContent = "▶";
      break;
    case "resumed":
      state.paused = false;
      updateBadge("playing");
      document.getElementById("btn-play").textContent = "⏸";
      break;
    case "stopped":
      state.playing = false;
      state.paused = false;
      state.currentIndex = -1;
      updateNowPlaying(null);
      updateBadge("stopped");
      document.getElementById("btn-play").textContent = "▶";
      highlightActive(-1);
      resetProgress();
      break;
    case "playlist_end":
      state.playing = false;
      updateBadge("stopped");
      updateNowPlaying(null);
      highlightActive(-1);
      resetProgress();
      break;
    case "schedule_updated":
      state.schedule = ev.items ?? [];
      renderSchedule();
      break;
  }
}

function applyState(s) {
  state.currentIndex = s.index ?? -1;
  state.playing = s.running ?? false;
  state.paused = s.paused ?? false;

  if (s.items) {
    state.schedule = s.items;
    renderSchedule();
  }
  if (s.current_item) {
    updateNowPlaying(s.current_item);
  } else {
    updateNowPlaying(null);
  }

  if (state.playing && !state.paused) {
    updateBadge("playing");
    document.getElementById("btn-play").textContent = "⏸";
  } else if (state.paused) {
    updateBadge("paused");
    document.getElementById("btn-play").textContent = "▶";
  } else {
    updateBadge("stopped");
    document.getElementById("btn-play").textContent = "▶";
  }

  highlightActive(state.currentIndex);
}

// ------------------------------------------------------------------ //
// UI helpers                                                           //
// ------------------------------------------------------------------ //
function setConnStatus(status) {
  const dot   = document.getElementById("dot");
  const label = document.getElementById("conn-label");
  dot.className = "dot " + status;
  label.textContent = { connected: "Conectado", connecting: "Conectando…", disconnected: "Desconectado" }[status] ?? status;
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

function resetProgress() {
  document.getElementById("progress-fill").style.width = "0%";
  document.getElementById("pos").textContent = "0:00";
  document.getElementById("dur").textContent = "0:00";
}

function highlightActive(index) {
  document.querySelectorAll(".schedule-item").forEach((el, i) => {
    el.classList.toggle("active", i === index);
  });
}

function fmt(secs) {
  if (secs == null || isNaN(secs)) return "0:00";
  secs = Math.floor(secs);
  const m = Math.floor(secs / 60);
  const s = String(secs % 60).padStart(2, "0");
  return `${m}:${s}`;
}

// Polling de posição a cada segundo via endpoint REST
function startProgressPolling() {
  clearInterval(state.posTimer);
  state.posTimer = setInterval(async () => {
    if (!state.playing || state.paused) return;
    try {
      const res = await fetch("/api/state");
      const s = await res.json();
      const pos = s.position ?? 0;
      const dur = s.duration ?? 0;
      document.getElementById("pos").textContent = fmt(pos);
      document.getElementById("dur").textContent = fmt(dur);
      const pct = dur > 0 ? Math.min((pos / dur) * 100, 100) : 0;
      document.getElementById("progress-fill").style.width = pct + "%";
    } catch (_) {}
  }, 1000);
}

// ------------------------------------------------------------------ //
// Roteiro                                                              //
// ------------------------------------------------------------------ //
function renderSchedule() {
  const list = document.getElementById("schedule-list");
  if (!state.schedule.length) {
    list.innerHTML = '<div class="empty">Roteiro vazio. Adicione itens ou edite o schedule.json.</div>';
    return;
  }

  list.innerHTML = "";
  state.schedule.forEach((item, i) => {
    const row = document.createElement("div");
    row.className = "schedule-item" + (i === state.currentIndex ? " active" : "");
    row.dataset.index = i;
    row.innerHTML = `
      <div class="item-index">${i + 1}</div>
      <input class="item-title" value="${esc(item.title)}" placeholder="Título" data-field="title" data-idx="${i}" />
      <input class="item-path"  value="${esc(item.path)}"  placeholder="Caminho do arquivo" data-field="path" data-idx="${i}" />
      <input class="item-dur"   value="${esc(item.duration ?? '')}" placeholder="Dur(s)" type="number" min="0" data-field="duration" data-idx="${i}" />
      <div class="item-actions">
        <button class="btn-play-item" title="Reproduzir este item" data-idx="${i}">▶</button>
        <button class="btn-delete"    title="Remover" data-idx="${i}">✕</button>
      </div>
    `;
    list.appendChild(row);

    // Edição inline
    row.querySelectorAll("input").forEach((inp) => {
      inp.addEventListener("change", () => {
        const idx   = parseInt(inp.dataset.idx);
        const field = inp.dataset.field;
        const val   = field === "duration" ? parseFloat(inp.value) || 0 : inp.value;
        state.schedule[idx][field] = val;
      });
    });

    row.querySelector(".btn-play-item").addEventListener("click", (e) => {
      e.stopPropagation();
      send({ action: "jump", index: i });
      send({ action: "play" });
    });

    row.querySelector(".btn-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      state.schedule.splice(i, 1);
      renderSchedule();
    });

    row.addEventListener("dblclick", () => {
      send({ action: "jump", index: i });
      send({ action: "play" });
    });
  });
}

function esc(str) {
  return String(str ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

// ------------------------------------------------------------------ //
// Log                                                                  //
// ------------------------------------------------------------------ //
function log(msg, type) {
  const div = document.getElementById("log");
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8);
  const entry = document.createElement("div");
  entry.className = `log-entry ev-${type}`;
  entry.innerHTML = `<span class="ts">${ts}</span><span class="ev">${type}</span><span class="msg">${esc(msg)}</span>`;
  div.appendChild(entry);
  div.scrollTop = div.scrollHeight;
}

// ------------------------------------------------------------------ //
// Botões                                                               //
// ------------------------------------------------------------------ //
document.getElementById("btn-play").addEventListener("click", () => send({ action: "pause" }));
document.getElementById("btn-stop").addEventListener("click", () => send({ action: "stop" }));
document.getElementById("btn-next").addEventListener("click", () => send({ action: "next" }));
document.getElementById("btn-prev").addEventListener("click", () => send({ action: "prev" }));

document.getElementById("btn-play").addEventListener("click", () => {
  if (!state.playing) send({ action: "play" });
});

// Simplificando: play quando não reproduzindo, pause/resume quando reproduzindo
document.getElementById("btn-play").replaceWith(
  (() => {
    const btn = document.createElement("button");
    btn.id = "btn-play";
    btn.title = "Play / Pause";
    btn.textContent = "▶";
    btn.addEventListener("click", () => {
      if (!state.playing) {
        send({ action: "play" });
      } else {
        send({ action: "pause" });
      }
    });
    return btn;
  })()
);

document.getElementById("btn-reload").addEventListener("click", () => {
  send({ action: "reload_schedule" });
  log("Recarregando roteiro do disco…", "info");
});

document.getElementById("btn-save").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/schedule", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.schedule),
    });
    if (res.ok) log("Roteiro salvo com sucesso", "info");
    else log("Erro ao salvar roteiro", "error");
  } catch (err) {
    log(`Erro: ${err.message}`, "error");
  }
});

document.getElementById("btn-add").addEventListener("click", () => {
  state.schedule.push({
    id: `item-${Date.now()}`,
    title: "Novo item",
    path: "",
    duration: 0,
  });
  renderSchedule();
});

document.getElementById("btn-clear-log").addEventListener("click", () => {
  document.getElementById("log").innerHTML = "";
});

// ------------------------------------------------------------------ //
// Bootstrap                                                            //
// ------------------------------------------------------------------ //
async function init() {
  // Carrega roteiro via REST antes de abrir WS
  try {
    const res = await fetch("/api/schedule");
    state.schedule = await res.json();
    renderSchedule();
  } catch (_) {}

  connect();
  startProgressPolling();
}

init();
