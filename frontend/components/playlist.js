/* PlayLine — Roteiro: renderização, drag & drop e miniaturas */

// thumbCache[path] = { state: 'loading'|'done'|'error', url: string, pending: imgEl[] }
const thumbCache = {};
const durLoading = new Set(); // paths com carregamento de duração em andamento
let dragSrcIdx  = null;
let libDragFile = null;

const THUMB_PREFIX = "playline_thumb:";

function thumbFromStorage(path) {
  try { return localStorage.getItem(THUMB_PREFIX + path); } catch (_) { return null; }
}

function thumbToStorage(path, url) {
  try { localStorage.setItem(THUMB_PREFIX + path, url); } catch (_) {}
}

// Carrega apenas os metadados do vídeo para obter a duração quando ela não está definida.
// Chamado sempre que um item pode ter duration === 0, independente do cache de thumbnail.
function ensureDuration(path) {
  const idx = state.schedule.findIndex(it => it.path === path);
  if (idx < 0) return;
  if (state.schedule[idx].duration > 0) return;
  if (durLoading.has(path)) return;

  durLoading.add(path);
  const v = document.createElement("video");
  v.muted = true;
  v.preload = "metadata";
  v.src = "/media?path=" + encodeURIComponent(path);
  v.addEventListener("loadedmetadata", () => {
    const i = state.schedule.findIndex(it => it.path === path);
    if (i >= 0 && !state.schedule[i].duration) {
      state.schedule[i].duration = Math.round(v.duration);
      const durEl = document.querySelector(`.item-dur[data-idx="${i}"]`);
      if (durEl) durEl.value = state.schedule[i].duration;
      updateStartTimes();
    }
    durLoading.delete(path);
    v.src = "";
  });
  v.addEventListener("error", () => { durLoading.delete(path); v.src = ""; });
}

// ------------------------------------------------------------------ //
// Miniaturas                                                           //
// ------------------------------------------------------------------ //
function generateThumb(path, imgEl) {
  if (!path) return;

  // Garante duração carregada independente do estado do thumbnail
  ensureDuration(path);

  const entry = thumbCache[path];

  // Cache em memória já resolvido
  if (entry) {
    if (entry.state === "done")    { imgEl.src = entry.url; return; }
    if (entry.state === "loading") { entry.pending.push(imgEl); return; }
    return; // error — não tenta de novo
  }

  // Thumb persistida no localStorage
  const stored = thumbFromStorage(path);
  if (stored) {
    thumbCache[path] = { state: "done", url: stored, pending: [] };
    imgEl.src = stored;
    return;
  }

  // Primeira vez — gera via vídeo oculto (duração + frame)
  thumbCache[path] = { state: "loading", url: "", pending: [imgEl] };

  const v = document.createElement("video");
  v.muted = true;
  v.preload = "metadata";
  v.src = "/media?path=" + encodeURIComponent(path);

  v.addEventListener("loadedmetadata", () => {
    // duração já é gerenciada por ensureDuration; aqui só avança para o frame
    v.currentTime = Math.min(2, (v.duration || 0) * 0.1 || 1);
  });

  v.addEventListener("seeked", () => {
    const canvas = document.createElement("canvas");
    canvas.width = 112; canvas.height = 63;
    canvas.getContext("2d").drawImage(v, 0, 0, 112, 63);
    const url = canvas.toDataURL("image/jpeg", 0.8);
    thumbToStorage(path, url);
    const cache = thumbCache[path];
    cache.state = "done";
    cache.url = url;
    cache.pending.forEach(el => { el.src = url; });
    cache.pending = [];
    v.src = "";
  });

  v.addEventListener("error", () => {
    thumbCache[path].state = "error";
    thumbCache[path].pending = [];
    v.src = "";
  });
}

// ------------------------------------------------------------------ //
// Horários                                                             //
// ------------------------------------------------------------------ //
function calcStartTimes() {
  const n = state.schedule.length;
  const times = new Array(n).fill(null);
  const idx = state.currentIndex;
  if (idx < 0 || !state.playing || !state.currentItemStartTime) return times;

  times[idx] = new Date(state.currentItemStartTime);  // ms timestamp → Date
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
  const total = state.schedule.slice(state.currentIndex).reduce((s, it) => s + (it.duration || 0), 0);
  if (!state.currentItemStartTime) return total;
  const pausedMs = (state.totalPausedMs || 0) + (state.pausedAt ? Date.now() - state.pausedAt : 0);
  const elapsed = Math.max(0, (Date.now() - state.currentItemStartTime - pausedMs) / 1000);
  return Math.max(0, total - elapsed);
}

function updateStartTimes() {
  const times = calcStartTimes();
  times.forEach((t, i) => {
    const el = document.querySelector(`.item-start[data-idx="${i}"]`);
    if (el) el.textContent = fmtTime(t);
  });

  const secs = calcRemaining();
  const rem = document.getElementById("remaining-time");
  if (rem) rem.textContent = secs > 0 ? fmt(secs) : "—";

  const nextEl = document.getElementById("next-clip-time");
  if (nextEl) {
    const nextIdx = state.currentIndex + 1;
    const nextStart = times[nextIdx];
    nextEl.textContent = nextStart ? fmtTime(nextStart) : "—";
  }
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

  // Captura as imagens já renderizadas no DOM antes de destruí-las
  const domThumbs = {};
  list.querySelectorAll(".schedule-item").forEach(row => {
    const img  = row.querySelector(".item-thumb");
    const path = row.querySelector("input[data-field='path']")?.value;
    if (img && path && img.src && img.src.startsWith("data:")) {
      domThumbs[path] = img.src;
      // garante que o cache em memória está sincronizado
      if (!thumbCache[path] || thumbCache[path].state !== "done") {
        thumbCache[path] = { state: "done", url: img.src, pending: [] };
      }
    }
  });

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

    if (item.path) {
      const imgEl = row.querySelector(".item-thumb");
      ensureDuration(item.path);  // sempre, independente do cache de thumbnail
      if (domThumbs[item.path]) {
        imgEl.src = domThumbs[item.path];
      } else {
        generateThumb(item.path, imgEl);
      }
    }

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
          generateThumb(val, row.querySelector(".item-thumb"));
        }

        updateStartTimes();
      });
      inp.addEventListener("click", e => e.stopPropagation());
    });

    row.querySelector(".btn-play-item").addEventListener("click", e => {
      e.stopPropagation();
      send({ action: "jump", index: i });
    });

    row.querySelector(".btn-delete").addEventListener("click", e => {
      e.stopPropagation();
      state.schedule.splice(i, 1);
      renderSchedule();
    });

    row.addEventListener("dblclick", () => {
      send({ action: "jump", index: i });
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
