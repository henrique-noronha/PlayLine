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

function updateScheduleSelectionUI() {
  // Menu "···" com opções do roteiro
  let btnMenu = document.getElementById("btn-schedule-menu");
  if (!btnMenu) {
    btnMenu = document.createElement("button");
    btnMenu.id = "btn-schedule-menu";
    btnMenu.title = "Opções do roteiro";
    btnMenu.textContent = "···";

    const dropdown = document.createElement("div");
    dropdown.id = "schedule-menu-dropdown";
    dropdown.innerHTML = `
      <div class="sch-menu-item" id="sch-menu-duplicate">⎘ Duplicar roteiro</div>
      <div class="sch-menu-separator"></div>
      <div class="sch-menu-item" id="sch-menu-clear">🗑 Limpar roteiro</div>
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
function ensureDuration(path) {
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
    // error — não tenta de novo; marca o item como inválido
    imgEl.closest(".lib-item, .schedule-item")?.classList.add("invalid");
    return;
  }

  // Thumb persistida no localStorage (inclui estado de erro persistido)
  const stored = thumbFromStorage(path);
  if (stored) {
    if (stored === "__error__") {
      thumbCache[path] = { state: "error", url: "", pending: [] };
      imgEl.closest(".lib-item, .schedule-item")?.classList.add("invalid");
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
    cache.pending.forEach(el => { el.src = url; });
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
        cache.pending.forEach(el => { el.src = url; });
        cache.pending = [];
      })
      .catch(() => {
        cache.state = "error";
        cache.pending.forEach(el => {
          el.closest(".lib-item, .schedule-item")?.classList.add("invalid");
        });
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
    log(`Erro ao sincronizar ordem: ${err.message}`, "error");
  }
}

function addFromLibrary(file, atIndex) {
  const newItem = { id: `item-${Date.now()}`, title: file.name, path: file.path, duration: 0 };
  state.schedule.splice(atIndex, 0, newItem);
  renderSchedule();
  syncOrderToServer();
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
      + (item.clip_overlays ? " has-clip-overlays" : "");
    row.dataset.index = i;
    row.setAttribute("draggable", isLocked ? "false" : "true");

    row.innerHTML = `
      <div class="item-drag" title="${isLocked ? "Em reprodução" : "Arrastar"}">${isLocked ? "▶" : "⠿"}</div>
      <div class="item-index">${i + 1}</div>
      <img class="item-thumb" draggable="false" src="" alt="" />
      <div class="item-meta">
        <span class="item-title" title="${esc(displayTitle)}">${esc(displayTitle)}</span>
        <input class="item-path"  value="${esc(item.path)}"   placeholder="Caminho do arquivo" data-field="path" data-idx="${i}" />
      </div>
      <div class="item-time">
        <span class="item-start" data-idx="${i}">${fmtTime(startTimes[i])}</span>
        <span class="item-date ${isToday(startTimes[i]) ? "" : "future"}" data-idx="${i}">${fmtDate(startTimes[i])}</span>
        <span class="item-dur"  data-idx="${i}">${item.duration > 0 ? fmt(item.duration) : "—"}</span>
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
      imgEl.addEventListener("error", () => row.classList.add("invalid"), { once: true });
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
      openClipOverlayPanel(item, i, e.currentTarget);
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
}

// Drag & Drop                                                          

function initDnD(list) {
  list.querySelectorAll(".schedule-item").forEach((row, i) => {
    row.addEventListener("dragstart", e => {
      if (libDragFile) return;
      if (state.playing && i === state.currentIndex) { e.preventDefault(); return; }
      document.querySelectorAll(".schedule-item.editing").forEach(r => r.classList.remove("editing"));
      dragSrcIdx = i;
      e.dataTransfer.effectAllowed = "move";
      setTimeout(() => row.classList.add("dragging"), 0);
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      list.querySelectorAll(".schedule-item").forEach(el => el.classList.remove("drag-over"));
      list.classList.remove("drag-over");
    });
    row.addEventListener("dragover", e => {
      if (state.playing && i <= state.currentIndex) return; // não aceita drop sobre/antes do clipe em execução
      e.preventDefault();
      e.dataTransfer.dropEffect = libDragFile ? "copy" : "move";
      list.querySelectorAll(".schedule-item").forEach(el => el.classList.remove("drag-over"));
      list.classList.remove("drag-over");
      row.classList.add("drag-over");
    });
    row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
    row.addEventListener("drop", e => {
      if (state.playing && i <= state.currentIndex) return; // bloqueia drop sobre/antes do clipe em execução
      e.preventDefault();
      row.classList.remove("drag-over");
      const libRaw = e.dataTransfer.getData("library-file");
      if (libRaw) {
        addFromLibrary(JSON.parse(libRaw), i);
        libDragFile = null;
        return;
      }
      if (dragSrcIdx === null || dragSrcIdx === i) return;
      if (state.playing && dragSrcIdx === state.currentIndex) return; // não move o clipe em execução
      const currentId = state.currentIndex >= 0 ? state.schedule[state.currentIndex]?.id : null;
      const [moved] = state.schedule.splice(dragSrcIdx, 1);
      state.schedule.splice(i, 0, moved);
      if (currentId) state.currentIndex = state.schedule.findIndex(it => it.id === currentId);
      dragSrcIdx = null;
      renderSchedule();
      syncOrderToServer();
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
        <button class="btn-logo-toggle cop-tog" id="cop-tog-1">⏻</button>
        <div class="cop-pick-wrap">
          <button class="cop-pbtn" id="cop-pbtn-1">— ▾</button>
          <div class="logo-picker-dropdown" id="cop-pdd-1"></div>
        </div>
      </div>
      <div class="cop-row">
        <span class="cop-lbl">Logo 2</span>
        <button class="btn-logo-toggle cop-tog" id="cop-tog-2">⏻</button>
        <div class="cop-pick-wrap">
          <button class="cop-pbtn" id="cop-pbtn-2">— ▾</button>
          <div class="logo-picker-dropdown" id="cop-pdd-2"></div>
        </div>
      </div>
      <div class="cop-row">
        <span class="cop-lbl">Hora / Temp.</span>
        <button class="btn-logo-toggle cop-tog" id="cop-tog-text">⏻</button>
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

// ─────────────────────────────────────────────────────────────────────────────

// Drop na área vazia do roteiro — registrado uma única vez (não dentro de initDnD)
(function setupListDrop() {
  const list = document.getElementById("schedule-list");

  list.addEventListener("dragover", e => {
    if (e.target.closest(".schedule-item")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = libDragFile ? "copy" : "move";
    list.classList.add("drag-over");
  });

  list.addEventListener("dragleave", e => {
    if (!list.contains(e.relatedTarget)) list.classList.remove("drag-over");
  });

  list.addEventListener("drop", e => {
    if (e.target.closest(".schedule-item")) return;
    e.preventDefault();
    list.classList.remove("drag-over");
    const libRaw = e.dataTransfer.getData("library-file");
    if (libRaw) {
      addFromLibrary(JSON.parse(libRaw), state.schedule.length);
      libDragFile = null;
    }
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
