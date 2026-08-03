/* PlayLine — Roteiro: renderização, drag & drop e miniaturas */

function showConfirm(message, onConfirm) {
  const backdrop = document.getElementById("confirm-modal");
  document.getElementById("confirm-modal-text").textContent = message;
  backdrop.style.display = "flex";
  const ok     = document.getElementById("confirm-modal-ok");
  const cancel = document.getElementById("confirm-modal-cancel");
  const close  = () => { backdrop.style.display = "none"; };
  ok.onclick     = () => { close(); onConfirm(); };
  cancel.onclick = close;
  backdrop.onclick = e => { if (e.target === backdrop) close(); };
}

// thumbCache[path] = { state: 'loading'|'done'|'error', url: string, pending: imgEl[] }
const thumbCache = {};
const durLoading = new Set(); // paths com carregamento de duração em andamento
let dragSrcIdx  = null;
let libDragFile = null;
let selectedScheduleIds = new Set();

const THUMB_PREFIX = "playline_thumb:";
const invalidPaths = new Set();
window._markPathInvalid = path => invalidPaths.add(path);
window._clearPathError  = path => {
  if (!invalidPaths.has(path)) return false;
  invalidPaths.delete(path);
  if (thumbCache[path]) {
    delete thumbCache[path];
    try { localStorage.removeItem(THUMB_PREFIX + path); } catch (_) {}
  }
  return true;
};

function parseTime(str) {
  if (!str || !str.trim()) return null;
  const parts = str.trim().split(":").map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0] * 3600 + parts[1] * 60 + (parts[2] || 0);
}

function fmtSec(secs) {
  if (secs == null || secs < 0) return "";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function effectiveDuration(item) {
  const dur = item.duration || 0;
  if (!dur || item.live) return dur;
  const start = item.start_time > 0 ? item.start_time : 0;
  const end   = item.end_time   > 0 ? item.end_time   : dur;
  return Math.max(0, end - start);
}

function hasTrim(item) {
  return !item.live && (item.start_time > 0 ||
    (item.end_time > 0 && item.end_time < (item.duration || Infinity)));
}

function updateScheduleSelectionUI() {
  // Menu "···" com opções do roteiro
  let btnMenu = document.getElementById("btn-schedule-menu");
  if (!btnMenu) {
    btnMenu = document.createElement("button");
    btnMenu.id = "btn-schedule-menu";
    btnMenu.title = "Opções do roteiro";
    btnMenu.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="13" viewBox="0 0 15 13" fill="currentColor"><circle cx="1.5" cy="1.5" r="1.5"/><rect x="4.5" y="0.5" width="10.5" height="2" rx="1"/><circle cx="1.5" cy="6.5" r="1.5"/><rect x="4.5" y="5.5" width="10.5" height="2" rx="1"/><circle cx="1.5" cy="11.5" r="1.5"/><rect x="4.5" y="10.5" width="10.5" height="2" rx="1"/></svg>';

    const dropdown = document.createElement("div");
    dropdown.id = "schedule-menu-dropdown";
    dropdown.innerHTML = `
      <div class="sch-menu-item" id="sch-menu-duplicate"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>Duplicar roteiro</div>
      <div class="sch-menu-item" id="sch-menu-save"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Salvar roteiro</div>
      <div class="sch-menu-item" id="sch-menu-load"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>Roteiros salvos</div>
      <div class="sch-menu-separator"></div>
      <div class="sch-menu-item" id="sch-menu-clear"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>Limpar roteiro</div>
    `;

    const wrap = document.createElement("div");
    wrap.id = "schedule-menu-wrap";
    wrap.appendChild(btnMenu);
    wrap.appendChild(dropdown);
    document.querySelector(".schedule-actions").prepend(wrap);

    btnMenu.addEventListener("click", e => {
      e.stopPropagation();
      dropdown.classList.toggle("open");
    });
    document.addEventListener("click", () => dropdown.classList.remove("open"));

    document.getElementById("sch-menu-duplicate").addEventListener("click", () => {
      dropdown.classList.remove("open");
      if (!state.schedule.length) return;
      const now = Date.now();
      const copies = state.schedule.map((it, i) => ({
        ...it,
        id: `item-${now + i}`
      }));
      state.schedule = [...state.schedule, ...copies];
      renderSchedule();
      syncOrderToServer();
    });

    document.getElementById("sch-menu-save").addEventListener("click", () => {
      dropdown.classList.remove("open");
      if (!state.schedule.length) return;
      openSaveSchedModal();
    });

    document.getElementById("sch-menu-load").addEventListener("click", () => {
      dropdown.classList.remove("open");
      openSavedSchedsModal();
    });

    document.getElementById("sch-menu-clear").addEventListener("click", () => {
      dropdown.classList.remove("open");
      if (!state.schedule.length) return;
      showConfirm("Tem certeza que deseja limpar o roteiro inteiro?", () => {
        const playingId = state.playing && state.currentIndex >= 0
          ? state.schedule[state.currentIndex]?.id : null;
        if (playingId) {
          state.schedule = state.schedule.filter(it => it.id === playingId);
        } else {
          state.schedule = [];
        }
        selectedScheduleIds.clear();
        renderSchedule();
        syncOrderToServer();
        showToast("Roteiro limpo", "info");
      });
    });
  }

  // Botão "remover selecionados"
  let btn = document.getElementById("btn-delete-selected");
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "btn-delete-selected";
    btn.title = "Remover selecionados";
    document.querySelector(".schedule-actions").appendChild(btn);
    btn.addEventListener("click", () => {
      const playingId = state.playing && state.currentIndex >= 0
        ? state.schedule[state.currentIndex]?.id : null;
      state.schedule = state.schedule.filter(it => !selectedScheduleIds.has(it.id));
      if (playingId) state.currentIndex = state.schedule.findIndex(it => it.id === playingId);
      selectedScheduleIds.clear();
      renderSchedule();
      syncOrderToServer();
    });
  }
  if (selectedScheduleIds.size > 0) {
    btn.textContent = `✕ ${selectedScheduleIds.size}`;
    btn.style.display = "";
  } else {
    btn.style.display = "none";
  }
}

function thumbFromStorage(path) {
  try { return localStorage.getItem(THUMB_PREFIX + path); } catch (_) { return null; }
}

function thumbToStorage(path, url) {
  try { localStorage.setItem(THUMB_PREFIX + path, url); } catch (_) {}
}

// Carrega apenas os metadados do vídeo para obter a duração quando ela não está definida.
// Chamado sempre que um item pode ter duration === 0, independente do cache de thumbnail.
// Placeholder SVG para itens de live stream
const _YT_LIVE_THUMB = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="112" height="63">' +
  '<rect width="112" height="63" fill="#111827"/>' +
  '<rect x="16" y="16" width="80" height="31" rx="4" fill="#dc2626"/>' +
  '<text x="56" y="37" font-family="Arial,sans-serif" font-size="11" font-weight="bold" ' +
  'fill="white" text-anchor="middle">&#9679; LIVE</text>' +
  '</svg>'
);

// Placeholder SVG para vídeos do YouTube (não-live)
const _YT_THUMB = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="112" height="63">' +
  '<rect width="112" height="63" fill="#111827"/>' +
  '<rect x="16" y="16" width="80" height="31" rx="4" fill="#cc0000"/>' +
  '<text x="56" y="37" font-family="Arial,sans-serif" font-size="11" font-weight="bold" ' +
  'fill="white" text-anchor="middle">Youtube</text>' +
  '</svg>'
);

function ensureDuration(path) {
  // Itens de URL (live streams) não têm duração via /media
  if (!path || path.startsWith("http")) return;
  // Retorna apenas se TODAS as ocorrências do path já têm duração
  if (!state.schedule.some(it => it.path === path && !(it.duration > 0))) return;
  if (durLoading.has(path)) return;  // já carregando; handler atualizará todas

  durLoading.add(path);
  const v = document.createElement("video");
  v.muted = true;
  v.preload = "metadata";
  v.src = "/media?path=" + encodeURIComponent(path);
  v.addEventListener("loadedmetadata", () => {
    const dur = Math.round(v.duration);
    let updated = false;
    state.schedule.forEach((it, i) => {
      if (it.path === path && !(it.duration > 0)) {
        state.schedule[i].duration = dur;
        const durEl = document.querySelector(`.item-dur[data-idx="${i}"]`);
        if (durEl) durEl.textContent = fmt(dur);
        updated = true;
      }
    });
    if (updated) updateStartTimes();
    durLoading.delete(path);
    v.src = "";
  }, { once: true });
  v.addEventListener("error", () => { durLoading.delete(path); v.src = ""; }, { once: true });
}


// Miniaturas                                                           
function generateThumb(path, imgEl) {
  if (!path) return;

  // Garante duração carregada independente do estado do thumbnail
  ensureDuration(path);

  const entry = thumbCache[path];

  // Cache em memória já resolvido
  if (entry) {
    if (entry.state === "done")    { imgEl.src = entry.url; return; }
    if (entry.state === "loading") { entry.pending.push(imgEl); return; }
    // error — não tenta de novo; thumbnail indisponível mas arquivo pode ser válido
    return;
  }

  // Thumb persistida no localStorage (inclui estado de erro persistido)
  const stored = thumbFromStorage(path);
  if (stored) {
    if (stored === "__error__") {
      thumbCache[path] = { state: "error", url: "", pending: [] };
      // thumbnail indisponível mas não invalida o item
      return;
    }
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
    v.currentTime = Math.min(2, (v.duration || 0) * 0.1 || 1);
  }, { once: true });

  v.addEventListener("seeked", () => {
    const canvas = document.createElement("canvas");
    canvas.width = 112; canvas.height = 63;
    canvas.getContext("2d").drawImage(v, 0, 0, 112, 63);
    const url = canvas.toDataURL("image/jpeg", 0.8);
    thumbToStorage(path, url);
    const cache = thumbCache[path];
    cache.state = "done";
    cache.url = url;
    cache.pending.forEach(el => {
      el.src = url;
      el.closest(".lib-item, .schedule-item")?.classList.remove("invalid");
    });
    cache.pending = [];
    v.src = "";
  }, { once: true });

  v.addEventListener("error", () => {
    const cache = thumbCache[path];
    if (!cache || cache.state !== "loading") return;
    cache.state = "error";
    v.src = "";
    fetch("/api/thumbnail?path=" + encodeURIComponent(path))
      .then(res => { if (!res.ok) throw 0; return res.blob(); })
      .then(blob => {
        const url = URL.createObjectURL(blob);
        thumbToStorage(path, url);
        cache.state = "done";
        cache.url   = url;
        cache.pending.forEach(el => {
          el.src = url;
          el.closest(".lib-item, .schedule-item")?.classList.remove("invalid");
        });
        cache.pending = [];
      })
      .catch(() => {
        cache.state = "error";
        // Browser + ffmpeg falharam → arquivo genuinamente ilegível
        invalidPaths.add(path);
        cache.pending.forEach(el => el.closest(".lib-item, .schedule-item")?.classList.add("invalid"));
        cache.pending = [];
        thumbToStorage(path, "__error__");
      });
  }, { once: true });
}


// Horários

function fmtDate(date) {
  if (!date) return "";
  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

function isToday(date) {
  if (!date) return true;
  const now = new Date();
  return date.getDate() === now.getDate() &&
         date.getMonth() === now.getMonth() &&
         date.getFullYear() === now.getFullYear();
}

function calcStartTimes() {
  const n = state.schedule.length;
  const times = new Array(n).fill(null);
  const idx = state.currentIndex;
  if (idx < 0 || !state.playing || !state.currentItemStartTime) return times;

  times[idx] = new Date(state.currentItemStartTime);

  // Para de calcular ao encontrar um live stream — duração indeterminada
  for (let i = idx + 1; i < n; i++) {
    const prev = state.schedule[i - 1];
    if (prev.live) break;
    times[i] = new Date(times[i - 1].getTime() + effectiveDuration(prev) * 1000);
  }
  for (let i = idx - 1; i >= 0; i--) {
    times[i] = new Date(times[i + 1].getTime() - effectiveDuration(state.schedule[i]) * 1000);
  }
  return times;
}

function calcRemaining() {
  if (!state.playing || state.currentIndex < 0) return 0;
  // Live stream em reprodução: sem como saber o tempo restante
  const currentItem = state.schedule[state.currentIndex];
  if (currentItem?.live) return 0;
  const total = state.schedule.slice(state.currentIndex).reduce((s, it) => {
    if (it.live) return s; // para de somar ao encontrar um live
    return s + effectiveDuration(it);
  }, 0);
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
    const de = document.querySelector(`.item-date[data-idx="${i}"]`);
    if (de) {
      de.textContent = fmtDate(t);
      de.classList.toggle("future", !!t && !isToday(t));
    }
  });

  const secs = calcRemaining();
  const rem = document.getElementById("remaining-time");
  if (rem) rem.textContent = secs > 0 ? fmt(secs) : "—";

  const nextEl = document.getElementById("next-clip-time");
  if (nextEl) {
    const nextIdx = state.currentIndex + 1;
    const nextStart = times[nextIdx];
    nextEl.textContent = nextStart ? nextStart.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
  }
}

function highlightActive(index) {
  document.querySelectorAll(".schedule-item").forEach((el, i) => {
    el.classList.toggle("active", i === index);
    const locked = state.playing && i === index;
    el.classList.toggle("locked", locked);
    el.setAttribute("draggable", locked ? "false" : "true");
    const drag = el.querySelector(".item-drag");
    if (drag) {
      drag.textContent = locked ? "▶" : "⠿";
      drag.title      = locked ? "Em reprodução" : "Arrastar";
    }
  });
}

// Sincronização com servidor                                           

async function syncOrderToServer() {
  try {
    await fetch("/api/schedule", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.schedule),
    });
  } catch (err) {
    log("Erro ao salvar a ordem do roteiro", "error");
  }
}

const _AUDIO_EXTS_PL = new Set([".mp3", ".wav", ".aac", ".m4a"]);

function addFromLibrary(file, atIndex) {
  const newItem = { id: `item-${Date.now()}`, title: file.name, path: file.path, duration: 0 };
  state.schedule.splice(atIndex, 0, newItem);
  renderSchedule();
  syncOrderToServer();
  const ext = file.path.slice(file.path.lastIndexOf(".")).toLowerCase();
  if (_AUDIO_EXTS_PL.has(ext) && typeof showToast === "function")
    showToast("♪ Arquivo de áudio — sem imagem no roteiro", "warn");
}

// Renderização                                                         //

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
    _refreshLibSchedBadges();
    return;
  }

  state.schedule.forEach((item, i) => {
    const displayTitle = (item.title && item.title !== "Novo item")
      ? item.title
      : (item.path ? item.path.split(/[/\\]/).pop().replace(/\.[^.]+$/, "") : "Novo item");

    const isLocked = state.playing && i === state.currentIndex;
    const row = document.createElement("div");
    row.className = "schedule-item"
      + (i === state.currentIndex ? " active" : "")
      + (isLocked ? " locked" : "")
      + (item.clip_overlays ? " has-clip-overlays" : "")
      + (hasTrim(item) ? " has-trim" : "")
      + (item.path && invalidPaths.has(item.path) ? " invalid" : "");
    row.dataset.index = i;
    row.setAttribute("draggable", isLocked ? "false" : "true");

    row.innerHTML = `
      <div class="item-drag" title="${isLocked ? "Em reprodução" : "Arrastar"}">${isLocked ? "▶" : "⠿"}</div>
      <div class="item-index">${i + 1}</div>
      <img class="item-thumb" draggable="false" alt="" />
      <div class="item-meta">
        <span class="item-title" title="${esc(displayTitle)}">${esc(displayTitle)}</span>
        <input class="item-path"  value="${esc(item.path)}"   placeholder="Caminho do arquivo" data-field="path" data-idx="${i}" />
      </div>
      <div class="item-time">
        <span class="item-start" data-idx="${i}">${fmtTime(startTimes[i])}</span>
        <span class="item-date ${isToday(startTimes[i]) ? "" : "future"}" data-idx="${i}">${fmtDate(startTimes[i])}</span>
        <span class="item-dur${item.live ? ' yt-live-dur' : ''}${hasTrim(item) ? ' trim-active' : ''}" data-idx="${i}">${item.live ? 'ao vivo' : (item.duration > 0 ? (hasTrim(item) ? ('✂ ' + fmt(effectiveDuration(item))) : fmt(item.duration)) : '—')}</span>
      </div>
      <div class="item-actions">
        ${!isLocked ? `<button class="btn-clip-overlay${item.clip_overlays ? ' configured' : ''}" title="Automação de overlays" data-idx="${i}">⚙</button>` : ''}
        <button class="btn-delete" title="Remover" data-idx="${i}">✕</button>
      </div>
    `;

    list.appendChild(row);
    if (selectedScheduleIds.has(item.id)) row.classList.add("selected");

    if (item.path) {
      const imgEl = row.querySelector(".item-thumb");
      if (item.live) {
        imgEl.src = _YT_LIVE_THUMB;
        imgEl.style.cursor = "pointer";
        imgEl.title = "Clique para visualizar a live";
        imgEl.addEventListener("click", e => {
          e.stopPropagation();
          if (typeof openYtPreview === "function") openYtPreview(item.path, imgEl);
        });
      } else if (item.type === "youtube_live") {
        imgEl.src = _YT_THUMB;
        imgEl.style.cursor = "pointer";
        imgEl.title = "Clique para pré-visualizar o vídeo";
        imgEl.addEventListener("click", e => {
          e.stopPropagation();
          if (typeof openYtPreview === "function") openYtPreview(item.path, imgEl);
        });
      } else {
        imgEl.addEventListener("error", () => { imgEl.style.visibility = "hidden"; }, { once: true });
        ensureDuration(item.path);
        if (domThumbs[item.path]) {
          imgEl.src = domThumbs[item.path];
        } else {
          generateThumb(item.path, imgEl);
        }
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
            row.querySelector(".item-title").textContent = autoTitle;
          }
          delete thumbCache[val];
          generateThumb(val, row.querySelector(".item-thumb"));
        }

        updateStartTimes();
      });
      inp.addEventListener("click", e => e.stopPropagation());
    });

    row.querySelector(".btn-clip-overlay")?.addEventListener("click", e => {
      e.stopPropagation();
      if (_gd && _gd.style.display !== "none" && _gdIdx === i) {
        _closeGd();
      } else {
        openGearMenu(item, i, e.currentTarget);
      }
    });

    row.querySelector(".btn-delete").addEventListener("click", e => {
      e.stopPropagation();
      const playingId = state.playing && state.currentIndex >= 0
        ? state.schedule[state.currentIndex]?.id : null;
      if (selectedScheduleIds.has(item.id) && selectedScheduleIds.size > 1) {
        // Batch: preserva o clipe em reprodução mesmo que esteja selecionado
        state.schedule = state.schedule.filter(it =>
          !selectedScheduleIds.has(it.id) || it.id === playingId
        );
        if (playingId) state.currentIndex = state.schedule.findIndex(it => it.id === playingId);
        selectedScheduleIds.clear();
      } else {
        if (playingId && item.id === playingId) return; // não remove clipe em reprodução
        state.schedule.splice(i, 1);
        selectedScheduleIds.delete(item.id);
        if (state.playing && state.currentIndex > i) state.currentIndex--;
      }
      renderSchedule();
      syncOrderToServer();
    });

    // Ativa edição ao clicar na área visual de um input (que tem pointer-events:none por padrão)
    row.addEventListener("click", e => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        e.stopPropagation();
        if (state.playing && i === state.currentIndex) return; // não seleciona clipe em reprodução
        if (selectedScheduleIds.has(item.id)) {
          selectedScheduleIds.delete(item.id);
          row.classList.remove("selected");
        } else {
          selectedScheduleIds.add(item.id);
          row.classList.add("selected");
        }
        updateScheduleSelectionUI();
        return;
      }
      for (const inp of row.querySelectorAll("input")) {
        const r = inp.getBoundingClientRect();
        if (e.clientX >= r.left && e.clientX <= r.right &&
            e.clientY >= r.top  && e.clientY <= r.bottom) {
          row.classList.add("editing");
          inp.focus();
          break;
        }
      }
    });
    row.addEventListener("focusin",  e => {
      if (e.target.tagName === "INPUT") row.classList.add("editing");
    });
    row.addEventListener("focusout", () => {
      setTimeout(() => {
        if (!row.contains(document.activeElement)) row.classList.remove("editing");
      }, 0);
    });
  });

  initDnD(list);
  updateStartTimes();
  updateScheduleSelectionUI();
  _refreshLibSchedBadges();
}

function _refreshLibSchedBadges() {
  const counts = new Map();
  state.schedule.forEach(it => { if (it.path) counts.set(it.path, (counts.get(it.path) || 0) + 1); });
  document.querySelectorAll(".lib-sched-badge").forEach(badge => {
    const n = counts.get(badge.dataset.path) || 0;
    badge.textContent = n > 0 ? String(n) : "";
    badge.style.display = n > 0 ? "inline-block" : "none";
  });
}
window._refreshLibSchedBadges = _refreshLibSchedBadges;

// Drag & Drop                                                          

function initDnD(list) {
  list.querySelectorAll(".schedule-item").forEach((row, i) => {
    row.addEventListener("dragstart", e => {
      if (libDragFile) return;
      if (state.playing && i === state.currentIndex) { e.preventDefault(); return; }
      document.querySelectorAll(".schedule-item.editing").forEach(r => r.classList.remove("editing"));
      dragSrcIdx = i;
      e.dataTransfer.effectAllowed = "move";
      window._schedDragging = true;
      setTimeout(() => row.classList.add("dragging"), 0);
    });
    row.addEventListener("dragend", () => {
      window._schedDragging = false;
      row.classList.remove("dragging");
      list.querySelector(".drop-indicator")?.remove();
    });
  });
}

// ── Popup de overlay por clipe ────────────────────────────────────────────────

let _cop    = null;
let _copIdx = null;

function _closeCop() {
  if (_cop) {
    _cop.querySelectorAll(".logo-picker-dropdown.open").forEach(d => d.classList.remove("open"));
    _cop.style.display = "none";
  }
  _copIdx = null;
}

function _copGetOrCreate() {
  if (_cop) return _cop;
  const el = document.createElement("div");
  el.id = "cop-popup";
  el.className = "cop-popup";
  el.style.display = "none";
  el.innerHTML = `
    <div class="cop-header">
      <label class="cop-enable-label">
        <input type="checkbox" id="cop-enable" />
        <span>Automatizar overlays</span>
      </label>
      <button id="cop-close" class="cop-close-btn">✕</button>
    </div>
    <div id="cop-body" class="cop-body">
      <div class="cop-row">
        <span class="cop-lbl">Logo 1</span>
        <button class="btn-logo-toggle cop-tog" id="cop-tog-1"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg></button>
        <div class="cop-pick-wrap">
          <button class="cop-pbtn" id="cop-pbtn-1">— ▾</button>
          <div class="logo-picker-dropdown" id="cop-pdd-1"></div>
        </div>
      </div>
      <div class="cop-row">
        <span class="cop-lbl">Logo 2</span>
        <button class="btn-logo-toggle cop-tog" id="cop-tog-2"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg></button>
        <div class="cop-pick-wrap">
          <button class="cop-pbtn" id="cop-pbtn-2">— ▾</button>
          <div class="logo-picker-dropdown" id="cop-pdd-2"></div>
        </div>
      </div>
      <div class="cop-row">
        <span class="cop-lbl">Hora / Temp.</span>
        <button class="btn-logo-toggle cop-tog" id="cop-tog-text"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg></button>
        <div class="cop-text-opts">
          <div class="logo-picker-item" id="cop-chk-time">
            <span class="logo-picker-check" id="cop-chk-time-mark">✓</span>
            <span class="logo-picker-name">Hora</span>
          </div>
          <div class="logo-picker-item" id="cop-chk-temp">
            <span class="logo-picker-check" id="cop-chk-temp-mark">✓</span>
            <span class="logo-picker-name">Temp.</span>
          </div>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(el);
  _cop = el;

  el.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", _closeCop);
  el.querySelector("#cop-close").addEventListener("click", _closeCop);

  el.querySelector("#cop-enable").addEventListener("change", function () {
    if (_copIdx === null) return;
    const item = state.schedule[_copIdx];
    if (!item) return;
    item.clip_overlays = this.checked ? _copDefaultConfig() : null;
    _copRefreshBody(item);
    _copMarkRow(_copIdx, !!item.clip_overlays);
    syncOrderToServer();
  });

  ["1", "2", "text"].forEach(slot => {
    el.querySelector(`#cop-tog-${slot}`).addEventListener("click", e => {
      e.stopPropagation();
      if (_copIdx === null) return;
      const item = state.schedule[_copIdx];
      if (!item?.clip_overlays) return;
      const key = slot === "text" ? "text" : `logo${slot}`;
      item.clip_overlays[key].active = !item.clip_overlays[key].active;
      _copRefreshBody(item);
      syncOrderToServer();
    });
  });

  [1, 2].forEach(slot => {
    const pbtn = el.querySelector(`#cop-pbtn-${slot}`);
    const pdd  = el.querySelector(`#cop-pdd-${slot}`);
    pbtn.addEventListener("click", e => {
      e.stopPropagation();
      const isOpen = pdd.classList.contains("open");
      el.querySelectorAll(".logo-picker-dropdown").forEach(d => d.classList.remove("open"));
      if (!isOpen) pdd.classList.add("open");
    });
    pdd.addEventListener("click", e => e.stopPropagation());
  });

  ["time", "temp"].forEach(key => {
    el.querySelector(`#cop-chk-${key}`).addEventListener("click", e => {
      e.stopPropagation();
      if (_copIdx === null) return;
      const item = state.schedule[_copIdx];
      if (!item?.clip_overlays?.text) return;
      item.clip_overlays.text[`show_${key}`] = !item.clip_overlays.text[`show_${key}`];
      _copRefreshBody(item);
      syncOrderToServer();
    });
  });

  return el;
}

function _copDefaultConfig() {
  const ls = (typeof _logoState !== "undefined") ? _logoState : {};
  const ts = (typeof _textState !== "undefined") ? _textState : {};
  return {
    logo1: { active: ls[1]?.active ?? false, filename: ls[1]?.filename ?? "", corner: ls[1]?.corner ?? "br" },
    logo2: { active: ls[2]?.active ?? false, filename: ls[2]?.filename ?? "", corner: ls[2]?.corner ?? "bl" },
    text:  { active: ts.active ?? false, show_time: ts.show_time ?? true, show_temp: ts.show_temp ?? true },
  };
}

function _copRefreshBody(item) {
  const el = _cop;
  if (!el) return;
  const co      = item.clip_overlays;
  const enabled = !!co;
  el.querySelector("#cop-enable").checked = enabled;
  const body = el.querySelector("#cop-body");
  body.style.opacity       = enabled ? "1" : "0.4";
  body.style.pointerEvents = enabled ? "" : "none";
  if (!enabled) return;

  [1, 2].forEach(slot => {
    const cfg = co[`logo${slot}`] || {};
    el.querySelector(`#cop-tog-${slot}`).classList.toggle("active", !!cfg.active);
    const fname = cfg.filename || "—";
    el.querySelector(`#cop-pbtn-${slot}`).textContent = fname + " ▾";

    const pdd   = el.querySelector(`#cop-pdd-${slot}`);
    const files = (typeof _logoFiles !== "undefined" ? _logoFiles : []);
    pdd.innerHTML = "";
    if (!files.length) {
      pdd.innerHTML = '<div class="logo-picker-empty">Pasta logos/ vazia</div>';
    } else {
      files.forEach(f => {
        const it  = document.createElement("div");
        it.className = "logo-picker-item";
        it.innerHTML = `<span class="logo-picker-check">${cfg.filename === f ? "✓" : ""}</span><span class="logo-picker-name">${esc(f)}</span>`;
        it.addEventListener("click", e => {
          e.stopPropagation();
          if (_copIdx === null) return;
          const itm = state.schedule[_copIdx];
          if (!itm?.clip_overlays) return;
          itm.clip_overlays[`logo${slot}`].filename = f;
          pdd.classList.remove("open");
          _copRefreshBody(itm);
          syncOrderToServer();
        });
        pdd.appendChild(it);
      });
    }
  });

  const text = co.text || {};
  el.querySelector("#cop-tog-text").classList.toggle("active", !!text.active);
  el.querySelector("#cop-chk-time-mark").style.visibility = text.show_time !== false ? "" : "hidden";
  el.querySelector("#cop-chk-temp-mark").style.visibility = text.show_temp !== false ? "" : "hidden";
}

function _copMarkRow(idx, hasConfig) {
  const row = document.querySelector(`.schedule-item[data-index="${idx}"]`);
  if (!row) return;
  row.classList.toggle("has-clip-overlays", hasConfig);
  const btn = row.querySelector(".btn-clip-overlay");
  if (btn) btn.classList.toggle("configured", hasConfig);
}

function openClipOverlayPanel(item, idx, anchorEl) {
  const el = _copGetOrCreate();
  _copIdx = idx;
  _copRefreshBody(item);

  // Exibe para poder medir altura real
  el.style.display = "block";
  const W    = 260;
  const H    = el.offsetHeight;
  const rect = anchorEl.getBoundingClientRect();
  let left = rect.left - W - 6;
  let top  = rect.top;
  if (left < 4) left = rect.right + 6;
  if (top + H > window.innerHeight - 8) top = window.innerHeight - H - 8;
  if (top < 4) top = 4;
  el.style.left = left + "px";
  el.style.top  = top  + "px";
}

// ── Gear menu (dropdown do botão ⚙) ──────────────────────────────────────────

let _gd = null;
let _gdItem = null, _gdIdx = null, _gdAnchor = null;

function _closeGd() {
  if (_gd) _gd.style.display = "none";
  _gdItem = null; _gdIdx = null; _gdAnchor = null;
}

function _getOrCreateGd() {
  if (_gd) return _gd;
  const el = document.createElement("div");
  el.id = "gear-dropdown";
  el.className = "gear-dropdown";
  el.style.display = "none";
  el.innerHTML = `
    <div class="gear-item" id="gd-overlays">⊡ Automação de overlays</div>
    <div class="gear-sep"></div>
    <div class="gear-item" id="gd-trim">✂ Recorte de clipe</div>
  `;
  document.body.appendChild(el);
  _gd = el;
  el.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", _closeGd);

  el.querySelector("#gd-overlays").addEventListener("click", () => {
    const item = _gdItem, idx = _gdIdx, anchor = _gdAnchor;
    _closeGd();
    if (idx !== null) openClipOverlayPanel(item, idx, anchor);
  });
  el.querySelector("#gd-trim").addEventListener("click", () => {
    if (el.querySelector("#gd-trim").classList.contains("disabled")) return;
    const item = _gdItem, idx = _gdIdx, anchor = _gdAnchor;
    _closeGd();
    if (idx !== null) openClipTrimPanel(item, idx, anchor);
  });
  return el;
}

function openGearMenu(item, idx, anchorEl) {
  const el = _getOrCreateGd();
  _gdItem = item; _gdIdx = idx; _gdAnchor = anchorEl;
  el.querySelector("#gd-overlays").classList.toggle("active", !!item.clip_overlays);
  el.querySelector("#gd-trim").classList.toggle("active", hasTrim(item));
  el.querySelector("#gd-trim").classList.toggle("disabled", !!item.live);
  el.style.display = "block";
  const W = el.offsetWidth, H = el.offsetHeight;
  const rect = anchorEl.getBoundingClientRect();
  let left = rect.left - W - 6, top = rect.top;
  if (left < 4) left = rect.right + 6;
  if (top + H > window.innerHeight - 8) top = window.innerHeight - H - 8;
  if (top < 4) top = 4;
  el.style.left = left + "px";
  el.style.top  = top  + "px";
}

// ── Popup de recorte de clipe ─────────────────────────────────────────────────

let _ct = null;
let _ctIdx = null;

function _closeCt() {
  if (_ct) _ct.style.display = "none";
  _ctIdx = null;
}

function _ctGetOrCreate() {
  if (_ct) return _ct;
  const el = document.createElement("div");
  el.id = "ct-popup";
  el.className = "ct-popup";
  el.style.display = "none";
  el.innerHTML = `
    <div class="ct-header">
      <span>✂ Recorte de clipe</span>
      <button id="ct-close" class="ct-close-btn">✕</button>
    </div>
    <div class="ct-body">
      <div class="ct-row">
        <label class="ct-lbl">Início</label>
        <input id="ct-start-inp" class="ct-inp" type="text" placeholder="0:00" autocomplete="off" spellcheck="false" />
      </div>
      <div class="ct-row">
        <label class="ct-lbl">Fim</label>
        <input id="ct-end-inp" class="ct-inp" type="text" placeholder="duração total" autocomplete="off" spellcheck="false" />
      </div>
      <div class="ct-dur-row">
        <span class="ct-dur-lbl">Duração efetiva</span>
        <span id="ct-eff-dur" class="ct-eff-dur">—</span>
      </div>
      <div class="ct-footer-row">
        <button id="ct-clear-btn" class="ct-clear-btn">Limpar</button>
        <button id="ct-ok-btn" class="ct-ok-btn">OK</button>
      </div>
    </div>
  `;
  document.body.appendChild(el);
  _ct = el;
  el.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", _closeCt);
  el.querySelector("#ct-close").addEventListener("click", _closeCt);

  const startInp = el.querySelector("#ct-start-inp");
  const endInp   = el.querySelector("#ct-end-inp");
  const effDur   = el.querySelector("#ct-eff-dur");

  function calcEff() {
    if (_ctIdx === null) return null;
    const item = state.schedule[_ctIdx];
    if (!item || !item.duration) return null;
    const s  = parseTime(startInp.value);
    const e2 = parseTime(endInp.value);
    const st = s  != null && s  > 0 ? s  : 0;
    const en = e2 != null && e2 > 0 ? e2 : item.duration;
    return Math.max(0, en - st);
  }

  function refreshEffDur() {
    const eff = calcEff();
    effDur.textContent = eff != null ? fmt(eff) : "—";

    if (_ctIdx === null) return;
    const item = state.schedule[_ctIdx];
    if (!item || !item.duration) return;
    const dur = item.duration;
    const s  = parseTime(startInp.value);
    const e2 = parseTime(endInp.value);
    const sErr  = s  != null && (s  < 0 || s  >= dur);
    const eErr  = e2 != null && (e2 <= 0 || e2 >  dur);
    const st = s  != null && s  > 0 ? s  : 0;
    const en = e2 != null && e2 > 0 ? e2 : dur;
    const crossErr = !sErr && !eErr && st >= en;
    startInp.classList.toggle("ct-inp-error", sErr || crossErr);
    endInp.classList.toggle("ct-inp-error",   eErr || crossErr);
  }

  function commit() {
    if (_ctIdx === null) return;
    const item = state.schedule[_ctIdx];
    if (!item || !item.duration) return;
    const dur = item.duration;

    let s  = parseTime(startInp.value);
    let e2 = parseTime(endInp.value);

    // Clampa ao intervalo válido e escreve de volta no campo
    if (s  != null) { s  = Math.max(0, Math.min(s,  dur)); startInp.value = s  > 0   ? fmtSec(s)  : ""; }
    if (e2 != null) { e2 = Math.max(0, Math.min(e2, dur)); endInp.value   = e2 < dur ? fmtSec(e2) : ""; }

    const st = s  != null && s  > 0 ? s  : 0;
    const en = e2 != null && e2 > 0 ? e2 : dur;
    if (st >= en) return; // configuração inválida: não salva

    startInp.classList.remove("ct-inp-error");
    endInp.classList.remove("ct-inp-error");

    if (s  != null && s  > 0)   item.start_time = s;  else delete item.start_time;
    if (e2 != null && e2 < dur) item.end_time   = e2; else delete item.end_time;
    _ctMarkRow(_ctIdx);
    updateStartTimes();
    syncOrderToServer();
  }

  startInp.addEventListener("input", refreshEffDur);
  endInp.addEventListener("input",   refreshEffDur);

  function commitAndClose() { commit(); _closeCt(); }
  el.querySelector("#ct-ok-btn").addEventListener("click", commitAndClose);
  startInp.addEventListener("keydown", e => { if (e.key === "Enter") commitAndClose(); });
  endInp.addEventListener("keydown",   e => { if (e.key === "Enter") commitAndClose(); });

  el.querySelector("#ct-clear-btn").addEventListener("click", () => {
    if (_ctIdx === null) return;
    const item = state.schedule[_ctIdx];
    if (!item) return;
    delete item.start_time; delete item.end_time;
    startInp.value = ""; endInp.value = "";
    effDur.textContent = item.duration > 0 ? fmt(item.duration) : "—";
    _ctMarkRow(_ctIdx);
    updateStartTimes();
    syncOrderToServer();
  });

  return el;
}

function _ctMarkRow(idx) {
  const row  = document.querySelector(`.schedule-item[data-index="${idx}"]`);
  const item = idx !== null ? state.schedule[idx] : null;
  if (!row || !item) return;
  const trimOn = hasTrim(item);
  row.classList.toggle("has-trim", trimOn);
  const durEl = row.querySelector(`.item-dur[data-idx="${idx}"]`);
  if (durEl && item.duration > 0 && !item.live) {
    durEl.className = `item-dur${trimOn ? ' trim-active' : ''}`;
    durEl.textContent = trimOn ? ('✂ ' + fmt(effectiveDuration(item))) : fmt(item.duration);
  }
  // Atualiza indicador no gear menu caso ainda esteja aberto
  if (_gd && _gdIdx === idx) {
    _gd.querySelector("#gd-trim").classList.toggle("active", trimOn);
  }
}

function openClipTrimPanel(item, idx, anchorEl) {
  const el = _ctGetOrCreate();
  _ctIdx = idx;
  const startInp = el.querySelector("#ct-start-inp");
  const endInp   = el.querySelector("#ct-end-inp");
  const effDur   = el.querySelector("#ct-eff-dur");
  startInp.value = item.start_time > 0 ? fmtSec(item.start_time) : "";
  endInp.value   = item.end_time   > 0 ? fmtSec(item.end_time)   : "";
  endInp.placeholder = item.duration > 0 ? fmtSec(item.duration) : "duração total";
  const eff = effectiveDuration(item);
  effDur.textContent = item.duration > 0 ? fmt(eff) : "—";
  el.style.display = "block";
  const W = 224, H = el.offsetHeight;
  const rect = anchorEl.getBoundingClientRect();
  let left = rect.left - W - 6, top = rect.top;
  if (left < 4) left = rect.right + 6;
  if (top + H > window.innerHeight - 8) top = window.innerHeight - H - 8;
  if (top < 4) top = 4;
  el.style.left = left + "px";
  el.style.top  = top  + "px";
}

// ─────────────────────────────────────────────────────────────────────────────

// Drop na área vazia do roteiro — registrado uma única vez (não dentro de initDnD)
(function setupListDrop() {
  const list = document.getElementById("schedule-list");
  let _dropIdx = null;
  let _indEl   = null;

  function _getInd() {
    if (!_indEl || !_indEl.isConnected) {
      _indEl = document.createElement("div");
      _indEl.className = "drop-indicator";
      list.appendChild(_indEl);
    }
    return _indEl;
  }

  function _hideInd() {
    _indEl?.remove();
    _indEl = null;
  }

  function _calcIdx(clientY) {
    const rows = list.querySelectorAll(".schedule-item");
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i].getBoundingClientRect();
      if (clientY < r.top + r.height / 2) return i;
    }
    return rows.length;
  }

  function _placeInd(idx) {
    const rows = [...list.querySelectorAll(".schedule-item")];
    const ind  = _getInd();
    const lTop = list.getBoundingClientRect().top;
    if (rows.length === 0) {
      ind.style.top = "4px";
    } else if (idx >= rows.length) {
      const r = rows[rows.length - 1].getBoundingClientRect();
      ind.style.top = (r.bottom - lTop + list.scrollTop) + "px";
    } else {
      const r = rows[idx].getBoundingClientRect();
      ind.style.top = (r.top - lTop + list.scrollTop) + "px";
    }
  }

  list.addEventListener("dragover", e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = libDragFile ? "copy" : "move";
    _dropIdx = _calcIdx(e.clientY);
    if (state.playing && _dropIdx <= state.currentIndex) { _hideInd(); return; }
    _placeInd(_dropIdx);
  });

  list.addEventListener("dragleave", e => {
    if (!list.contains(e.relatedTarget)) _hideInd();
  });

  list.addEventListener("drop", e => {
    e.preventDefault();
    _hideInd();
    const idx = _dropIdx ?? state.schedule.length;
    _dropIdx = null;
    if (state.playing && idx <= state.currentIndex) return;

    const multiRaw = e.dataTransfer.getData("library-files-multi");
    if (multiRaw) {
      const files = JSON.parse(multiRaw);
      const now = Date.now();
      files.forEach((f, j) => state.schedule.splice(idx + j, 0, {
        id: `item-${now + j}`, title: f.name, path: f.path, duration: 0,
      }));
      libDragFile = null;
      renderSchedule();
      syncOrderToServer();
      return;
    }

    const libRaw = e.dataTransfer.getData("library-file");
    if (libRaw) {
      addFromLibrary(JSON.parse(libRaw), idx);
      libDragFile = null;
      return;
    }

    // Reordenação
    if (dragSrcIdx === null) return;
    if (state.playing && dragSrcIdx === state.currentIndex) return;
    const insertAt = idx > dragSrcIdx ? idx - 1 : idx;
    if (dragSrcIdx === insertAt) { dragSrcIdx = null; return; }
    const currentId = state.currentIndex >= 0 ? state.schedule[state.currentIndex]?.id : null;
    const [moved] = state.schedule.splice(dragSrcIdx, 1);
    state.schedule.splice(insertAt, 0, moved);
    if (currentId) state.currentIndex = state.schedule.findIndex(it => it.id === currentId);
    dragSrcIdx = null;
    renderSchedule();
    syncOrderToServer();
  });

  document.addEventListener("click", e => {
    if (!e.target.closest(".schedule-item")) {
      document.querySelectorAll(".schedule-item.editing").forEach(r => r.classList.remove("editing"));
      if (!e.ctrlKey && !e.metaKey && selectedScheduleIds.size > 0) {
        selectedScheduleIds.clear();
        document.querySelectorAll(".schedule-item.selected").forEach(r => r.classList.remove("selected"));
        updateScheduleSelectionUI();
      }
    }
  });
})();
