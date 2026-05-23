/* PlayLine — Roteiro: renderização, drag & drop e miniaturas */

const thumbCache = {};
let dragSrcIdx  = null;   // índice no roteiro (reordenar)
let libDragFile = null;   // arquivo vindo da biblioteca

// ------------------------------------------------------------------ //
// Miniaturas                                                           //
// ------------------------------------------------------------------ //
function generateThumb(path, imgEl, scheduleIdx) {
  if (!path) return;
  if (thumbCache[path] && thumbCache[path] !== "loading") {
    imgEl.src = thumbCache[path];
    return;
  }
  if (thumbCache[path] === "loading") return;
  thumbCache[path] = "loading";

  const v = document.createElement("video");
  v.muted = true;
  v.preload = "metadata";
  v.src = "/media?path=" + encodeURIComponent(path);

  v.addEventListener("loadedmetadata", () => {
    if (scheduleIdx >= 0 && scheduleIdx < state.schedule.length) {
      if (!state.schedule[scheduleIdx].duration || state.schedule[scheduleIdx].duration === 0) {
        state.schedule[scheduleIdx].duration = Math.round(v.duration);
        const durEl = document.querySelector(`.item-dur[data-idx="${scheduleIdx}"]`);
        if (durEl) durEl.value = state.schedule[scheduleIdx].duration;
        updateStartTimes();
      }
    }
    v.currentTime = Math.min(2, (v.duration || 0) * 0.1 || 1);
  });

  v.addEventListener("seeked", () => {
    const canvas = document.createElement("canvas");
    canvas.width = 112; canvas.height = 63;
    canvas.getContext("2d").drawImage(v, 0, 0, 112, 63);
    const url = canvas.toDataURL("image/jpeg", 0.8);
    thumbCache[path] = url;
    imgEl.src = url;
    v.src = "";
  });

  v.addEventListener("error", () => { thumbCache[path] = ""; v.src = ""; });
}

// ------------------------------------------------------------------ //
// Horários                                                             //
// ------------------------------------------------------------------ //
function calcStartTimes() {
  const n = state.schedule.length;
  const times = new Array(n).fill(null);
  const idx = state.currentIndex;
  if (idx < 0 || !state.playing || !state.currentItemStartTime) return times;

  times[idx] = new Date(state.currentItemStartTime);
  for (let i = idx + 1; i < n; i++) {
    times[i] = new Date(times[i - 1].getTime() + (state.schedule[i - 1].duration || 0) * 1000);
  }
  for (let i = idx - 1; i >= 0; i--) {
    times[i] = new Date(times[i + 1].getTime() - (state.schedule[i].duration || 0) * 1000);
  }
  return times;
}

function calcRemaining() {
  if (!state.playing || state.currentIndex < 0) return 0;
  return state.schedule.slice(state.currentIndex).reduce((s, it) => s + (it.duration || 0), 0);
}

function updateStartTimes() {
  const times = calcStartTimes();
  times.forEach((t, i) => {
    const el = document.querySelector(`.item-start[data-idx="${i}"]`);
    if (el) el.textContent = fmtTime(t);
  });
  const rem = document.getElementById("remaining-time");
  const secs = calcRemaining();
  if (rem) rem.textContent = secs > 0 ? `— restante: ${fmt(secs)}` : "";
}

function highlightActive(index) {
  document.querySelectorAll(".schedule-item").forEach((el, i) => {
    el.classList.toggle("active", i === index);
  });
}

// ------------------------------------------------------------------ //
// Sincronização com servidor                                           //
// ------------------------------------------------------------------ //
async function syncOrderToServer() {
  try {
    await fetch("/api/schedule", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.schedule),
    });
  } catch (err) {
    log(`Erro ao sincronizar ordem: ${err.message}`, "error");
  }
}

function addFromLibrary(file, atIndex) {
  const newItem = { id: `item-${Date.now()}`, title: file.name, path: file.path, duration: 0 };
  state.schedule.splice(atIndex, 0, newItem);
  renderSchedule();
  syncOrderToServer();
}

// ------------------------------------------------------------------ //
// Renderização                                                         //
// ------------------------------------------------------------------ //
function renderSchedule() {
  const list = document.getElementById("schedule-list");
  list.innerHTML = "";
  const startTimes = calcStartTimes();

  if (!state.schedule.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Arraste vídeos da biblioteca para começar o roteiro";
    list.appendChild(empty);
    initDnD(list);
    return;
  }

  state.schedule.forEach((item, i) => {
    const displayTitle = (item.title && item.title !== "Novo item")
      ? item.title
      : (item.path ? item.path.split(/[/\\]/).pop().replace(/\.[^.]+$/, "") : "Novo item");

    const row = document.createElement("div");
    row.className = "schedule-item" + (i === state.currentIndex ? " active" : "");
    row.dataset.index = i;
    row.setAttribute("draggable", "true");

    row.innerHTML = `
      <div class="item-drag" title="Arrastar">⠿</div>
      <div class="item-index">${i + 1}</div>
      <img class="item-thumb" draggable="false" src="" alt="" />
      <div class="item-meta">
        <input class="item-title" value="${esc(displayTitle)}" placeholder="Título" data-field="title" data-idx="${i}" />
        <input class="item-path"  value="${esc(item.path)}"   placeholder="Caminho do arquivo" data-field="path" data-idx="${i}" />
      </div>
      <div class="item-time">
        <span class="item-start" data-idx="${i}">${fmtTime(startTimes[i])}</span>
        <input class="item-dur" value="${item.duration ?? ""}" placeholder="seg" type="number" min="0"
               data-field="duration" data-idx="${i}" title="Duração em segundos" />
      </div>
      <div class="item-actions">
        <button class="btn-play-item" title="Reproduzir este item" data-idx="${i}">▶</button>
        <button class="btn-delete"    title="Remover" data-idx="${i}">✕</button>
      </div>
    `;

    list.appendChild(row);

    if (item.path) generateThumb(item.path, row.querySelector(".item-thumb"), i);

    row.querySelectorAll("input").forEach(inp => {
      inp.addEventListener("change", () => {
        const idx = parseInt(inp.dataset.idx);
        const field = inp.dataset.field;
        const val = field === "duration" ? parseFloat(inp.value) || 0 : inp.value;
        state.schedule[idx][field] = val;

        if (field === "path" && val) {
          const autoTitle = val.split(/[/\\]/).pop().replace(/\.[^.]+$/, "");
          if (!state.schedule[idx].title || state.schedule[idx].title === "Novo item") {
            state.schedule[idx].title = autoTitle;
            row.querySelector(".item-title").value = autoTitle;
          }
          delete thumbCache[val];
          generateThumb(val, row.querySelector(".item-thumb"), idx);
        }

        updateStartTimes();
      });
      inp.addEventListener("click", e => e.stopPropagation());
    });

    row.querySelector(".btn-play-item").addEventListener("click", e => {
      e.stopPropagation();
      send({ action: "jump", index: i });
      send({ action: "play" });
    });

    row.querySelector(".btn-delete").addEventListener("click", e => {
      e.stopPropagation();
      state.schedule.splice(i, 1);
      renderSchedule();
    });

    row.addEventListener("dblclick", () => {
      send({ action: "jump", index: i });
      send({ action: "play" });
    });
  });

  initDnD(list);
  updateStartTimes();
}

// ------------------------------------------------------------------ //
// Drag & Drop                                                          //
// ------------------------------------------------------------------ //
function initDnD(list) {
  list.querySelectorAll(".schedule-item").forEach((row, i) => {
    row.addEventListener("dragstart", e => {
      if (libDragFile) return;
      dragSrcIdx = i;
      e.dataTransfer.effectAllowed = "move";
      setTimeout(() => row.classList.add("dragging"), 0);
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      list.querySelectorAll(".schedule-item, .schedule-drop-end").forEach(el => el.classList.remove("drag-over"));
    });
    row.addEventListener("dragover", e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = libDragFile ? "copy" : "move";
      list.querySelectorAll(".schedule-item, .schedule-drop-end").forEach(el => el.classList.remove("drag-over"));
      row.classList.add("drag-over");
    });
    row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
    row.addEventListener("drop", e => {
      e.preventDefault();
      row.classList.remove("drag-over");
      const libRaw = e.dataTransfer.getData("library-file");
      if (libRaw) {
        addFromLibrary(JSON.parse(libRaw), i);
        libDragFile = null;
        return;
      }
      if (dragSrcIdx === null || dragSrcIdx === i) return;
      const currentId = state.currentIndex >= 0 ? state.schedule[state.currentIndex]?.id : null;
      const [moved] = state.schedule.splice(dragSrcIdx, 1);
      state.schedule.splice(i, 0, moved);
      if (currentId) state.currentIndex = state.schedule.findIndex(it => it.id === currentId);
      dragSrcIdx = null;
      renderSchedule();
      syncOrderToServer();
    });
  });

  // Zona de drop no final do roteiro
  const dropEnd = document.createElement("div");
  dropEnd.className = "schedule-drop-end";
  dropEnd.textContent = "Solte aqui para adicionar ao final";
  list.appendChild(dropEnd);

  dropEnd.addEventListener("dragover", e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = libDragFile ? "copy" : "move";
    list.querySelectorAll(".schedule-item").forEach(el => el.classList.remove("drag-over"));
    dropEnd.classList.add("drag-over");
  });
  dropEnd.addEventListener("dragleave", () => dropEnd.classList.remove("drag-over"));
  dropEnd.addEventListener("drop", e => {
    e.preventDefault();
    dropEnd.classList.remove("drag-over");
    const libRaw = e.dataTransfer.getData("library-file");
    if (libRaw) {
      addFromLibrary(JSON.parse(libRaw), state.schedule.length);
      libDragFile = null;
    }
  });
}

// ------------------------------------------------------------------ //
// Botões do roteiro                                                    //
// ------------------------------------------------------------------ //
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
  state.schedule.push({ id: `item-${Date.now()}`, title: "Novo item", path: "", duration: 0 });
  renderSchedule();
});
