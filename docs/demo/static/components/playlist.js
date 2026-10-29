/* PlayLine — Roteiro: renderização, miniaturas, categorias e transições */

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
let selectedScheduleIds = new Set();

const THUMB_PREFIX = "playline_thumb:";
const invalidPaths = new Set();
window._markPathInvalid = path => invalidPaths.add(path);
window._clearPathError  = path => {
  if (!invalidPaths.has(path)) return false;
  invalidPaths.delete(path);
  _updateErrorCount();
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
    btnMenu.title = window.t("playlist.menu_title");
    btnMenu.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="13" viewBox="0 0 15 13" fill="currentColor"><circle cx="1.5" cy="1.5" r="1.5"/><rect x="4.5" y="0.5" width="10.5" height="2" rx="1"/><circle cx="1.5" cy="6.5" r="1.5"/><rect x="4.5" y="5.5" width="10.5" height="2" rx="1"/><circle cx="1.5" cy="11.5" r="1.5"/><rect x="4.5" y="10.5" width="10.5" height="2" rx="1"/></svg>';

    const dropdown = document.createElement("div");
    dropdown.id = "schedule-menu-dropdown";
    dropdown.innerHTML = `
      <div class="sch-menu-item" id="sch-menu-duplicate"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>${window.t("playlist.menu_duplicate")}</div>
      <div class="sch-menu-item" id="sch-menu-save"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>${window.t("playlist.menu_save")}</div>
      <div class="sch-menu-item" id="sch-menu-load"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>${window.t("playlist.menu_load")}</div>
      <div class="sch-menu-item" id="sch-menu-loop"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>${window.t("playlist.menu_loop")}</div>
      <div class="sch-menu-separator"></div>
      <div class="sch-menu-item" id="sch-menu-clear"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>${window.t("playlist.menu_clear")}</div>
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

    document.getElementById("sch-menu-loop").addEventListener("click", () => {
      dropdown.classList.remove("open");
      if (state.repeat) {
        showConfirm(window.t("playlist.confirm_disable_loop"), () => {
          state.repeat = false;
          fetch("/api/repeat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: false }),
          });
          updateLoopIndicator();
        });
      } else {
        state.repeat = true;
        fetch("/api/repeat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: true }),
        });
        updateLoopIndicator();
      }
    });

    document.getElementById("sch-menu-clear").addEventListener("click", () => {
      dropdown.classList.remove("open");
      if (!state.schedule.length) return;
      showConfirm(window.t("playlist.confirm_clear"), () => {
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
        showToast(window.t("playlist.cleared_toast"), "info");
      });
    });
  }

  // Botão "remover selecionados"
  let btn = document.getElementById("btn-delete-selected");
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "btn-delete-selected";
    btn.title = window.t("playlist.delete_selected");
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

// Placeholder SVG para dispositivos de captura (webcam, placa de captura)
const _CAPTURE_THUMB = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="112" height="63" viewBox="0 0 112 63">' +
  '<rect width="112" height="63" fill="#0c1116"/>' +
  '<rect x="18" y="12" width="76" height="44" rx="5" fill="#111827" stroke="#1e3a4a" stroke-width="1.5"/>' +
  '<circle cx="56" cy="34" r="13" fill="none" stroke="#1e3a4a" stroke-width="2"/>' +
  '<circle cx="56" cy="34" r="8" fill="none" stroke="#22d3ee" stroke-width="1.5" opacity=".7"/>' +
  '<circle cx="56" cy="34" r="3" fill="#22d3ee" opacity=".9"/>' +
  '<rect x="32" y="16" width="14" height="8" rx="2" fill="#1e3a4a"/>' +
  '<text x="56" y="59" font-family="Arial,sans-serif" font-size="7" fill="#22d3ee" opacity=".7" text-anchor="middle" letter-spacing=".5">CAPTURE</text>' +
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


// Fila de carregamento de mídia
// Miniatura e duração custam decodificação de vídeo. Sem fila, abrir uma pasta
// com 50 clipes dispara ~100 elementos <video> de uma vez, e numa máquina
// modesta isso disputa CPU com a reprodução que está no ar. Limita quantos
// rodam ao mesmo tempo e publica o progresso para a interface mostrar.
const _MEDIA_CONC    = 3;
const _MEDIA_TIMEOUT = 20000;  // rede lenta ou arquivo ruim não prende a fila
let _mediaActive  = 0;
let _mediaDone    = 0;
let _mediaTotal   = 0;
const _mediaQueue = [];

function _mediaEnqueue(task) {
  _mediaTotal++;
  _mediaQueue.push(task);
  _mediaReport();
  _mediaPump();
}

function _mediaPump() {
  while (_mediaActive < _MEDIA_CONC && _mediaQueue.length) {
    const task = _mediaQueue.shift();
    _mediaActive++;
    let settled = false;
    const done = () => {
      if (settled) return;   // tarefa pode sinalizar por mais de um caminho
      settled = true;
      _mediaActive--;
      _mediaDone++;
      _mediaReport();
      _mediaPump();
    };
    setTimeout(done, _MEDIA_TIMEOUT);
    try { task(done); } catch (_) { done(); }
  }
}

function _mediaReport() {
  const done = _mediaDone, total = _mediaTotal;
  if (total > 0 && done >= total) { _mediaDone = 0; _mediaTotal = 0; }  // leva concluída
  window._onMediaProgress?.(done, total);
}

// Duração em cache
// Duração de um arquivo não muda. Sem isto, trocar de pasta relê os metadados
// de todos os vídeos de novo, toda vez.
const DUR_PREFIX = "playline_dur:";

function durFromStorage(path) {
  try {
    const v = localStorage.getItem(DUR_PREFIX + path);
    return v === null ? null : Number(v);
  } catch (_) { return null; }
}

function durToStorage(path, secs) {
  try { localStorage.setItem(DUR_PREFIX + path, String(secs)); } catch (_) {}
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

  // Thumb persistida no localStorage por versões anteriores. Hoje o caminho
  // normal não grava mais aqui: o servidor responde com Cache-Control immutable
  // e quem guarda é o cache HTTP.
  const stored = thumbFromStorage(path);
  if (stored === "__error__") {
    // Erro gravado por versões anteriores: não serve de verdade (o arquivo pode
    // ter sido corrigido) e, reaproveitado, pulava a marcação de inválido, então
    // o item perdia a borda vermelha ao reabrir a interface. Descarta e testa de novo.
    try { localStorage.removeItem(THUMB_PREFIX + path); } catch (_) {}
  } else if (stored) {
    thumbCache[path] = { state: "done", url: stored, pending: [] };
    imgEl.src = stored;
    return;
  }

  thumbCache[path] = { state: "loading", url: "", pending: [imgEl] };
  _mediaEnqueue(done => _thumbFromServer(path, done));
}

// Caminho normal: o servidor já gera a miniatura com ffmpeg (mesmos 112x63) e
// guarda em disco, inclusive pré-aquecendo no boot. Custa um GET de JPEG em vez
// de decodificar vídeo no navegador, e o Cache-Control immutable evita repetir.
function _thumbFromServer(path, done) {
  const url = "/api/thumbnail?path=" + encodeURIComponent(path);
  const probe = new Image();
  probe.onload = () => {
    const cache = thumbCache[path];
    if (cache) {
      cache.state = "done";
      cache.url   = url;
      cache.pending.forEach(el => {
        el.src = url;
        el.closest(".lib-item, .schedule-item")?.classList.remove("invalid");
      });
      cache.pending = [];
    }
    done();
  };
  // Servidor sem ffmpeg, ou arquivo que o ffmpeg não abre: tenta pelo navegador.
  probe.onerror = () => _thumbFromBrowser(path, done);
  probe.src = url;
}

// Fallback: decodifica no navegador e desenha num canvas. Mais caro, por isso
// só roda quando o servidor não deu conta.
function _thumbFromBrowser(path, done) {
  const v = document.createElement("video");
  v.muted = true;
  v.preload = "metadata";

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
    if (cache) {
      cache.state = "done";
      cache.url = url;
      cache.pending.forEach(el => {
        el.src = url;
        el.closest(".lib-item, .schedule-item")?.classList.remove("invalid");
      });
      cache.pending = [];
    }
    v.src = "";
    done();
  }, { once: true });

  v.addEventListener("error", () => {
    const cache = thumbCache[path];
    v.src = "";
    if (cache && cache.state === "loading") {
      // Servidor e navegador falharam → arquivo genuinamente ilegível
      cache.state = "error";
      invalidPaths.add(path);
      cache.pending.forEach(el => el.closest(".lib-item, .schedule-item")?.classList.add("invalid"));
      cache.pending = [];
      // O erro não é gravado no localStorage: com o perfil persistente ele
      // sobreviveria entre aberturas e o arquivo nunca mais seria testado.
      _updateErrorCount();
    }
    done();
  }, { once: true });

  v.src = "/media?path=" + encodeURIComponent(path);
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

function updateLoopIndicator() {
  const indicator = document.getElementById("sch-loop-indicator");
  if (indicator) indicator.style.display = state.repeat ? "inline-flex" : "none";
  const menuItem = document.getElementById("sch-menu-loop");
  if (menuItem) menuItem.classList.toggle("loop-active", !!state.repeat);
}

function calcRemaining() {
  if (state.repeat) return Infinity;
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

function calcClipRemaining() {
  if (!state.playing || state.currentIndex < 0) return 0;
  const currentItem = state.schedule[state.currentIndex];
  if (!currentItem || currentItem.live) return 0;
  const dur = effectiveDuration(currentItem);
  if (!state.currentItemStartTime) return dur;
  const pausedMs = (state.totalPausedMs || 0) + (state.pausedAt ? Date.now() - state.pausedAt : 0);
  const elapsed = Math.max(0, (Date.now() - state.currentItemStartTime - pausedMs) / 1000);
  return Math.max(0, dur - elapsed);
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
  if (rem) rem.textContent = secs === Infinity ? "∞" : (secs > 0 ? fmt(secs) : "—");

  const clipSecs = calcClipRemaining();
  const clipRem = document.getElementById("clip-remaining-time");
  if (clipRem) clipRem.textContent = clipSecs > 0 ? fmt(clipSecs) : "—";

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
      drag.title      = locked ? window.t("playlist.playing_lock_title") : window.t("playlist.drag_title");
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
    log(window.t("logmsg.order_save_failed"), "error");
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
    showToast(window.t("library.audio_no_thumb_warn"), "warn");
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
    empty.textContent = window.t("playlist.empty");
    list.appendChild(empty);
    initDnD(list);
    _refreshLibSchedBadges();
    if (typeof window._onScheduleChangedForInputQuadrant === "function") window._onScheduleChangedForInputQuadrant();
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
      <div class="item-drag" title="${isLocked ? esc(window.t("playlist.playing_lock_title")) : esc(window.t("playlist.drag_title"))}">${isLocked ? "▶" : "⠿"}</div>
      <div class="item-index">${i + 1}</div>
      <img class="item-thumb" draggable="false" alt="" />
      <div class="item-meta">
        <span class="item-title-row"><span class="item-title" title="${esc(displayTitle)}">${esc(displayTitle)}</span>${_transitionTagHtml(item)}</span>
        <input class="item-path"  value="${esc(item.path)}"   placeholder="${esc(window.t("playlist.path_placeholder"))}" data-field="path" data-idx="${i}" />
      </div>
      ${_clipCategoryHtml(item)}
      <div class="item-time">
        <span class="item-start" data-idx="${i}">${fmtTime(startTimes[i])}</span>
        <span class="item-dur${item.live ? ' yt-live-dur' : ''}${hasTrim(item) ? ' trim-active' : ''}" data-idx="${i}">${item.live ? window.t('playlist.live_duration') : (item.duration > 0 ? (hasTrim(item) ? ('✂ ' + fmt(effectiveDuration(item))) : fmt(item.duration)) : '—')}</span>
        <span class="item-date ${isToday(startTimes[i]) ? "" : "future"}" data-idx="${i}">${fmtDate(startTimes[i])}</span>
      </div>
      <div class="item-actions">
        ${!isLocked ? `<button class="btn-clip-overlay${item.clip_overlays ? ' configured' : ''}" title="${esc(window.t('playlist.overlay_automation_title'))}" data-idx="${i}">⚙</button>` : ''}
        <button class="btn-delete" title="${esc(window.t('playlist.remove_title'))}" data-idx="${i}">✕</button>
      </div>
    `;

    list.appendChild(row);
    if (selectedScheduleIds.has(item.id)) row.classList.add("selected");

    if (item.path) {
      const imgEl = row.querySelector(".item-thumb");
      if (item.live) {
        const isCapture = item.type === "capture";
        imgEl.src = isCapture ? _CAPTURE_THUMB : _YT_LIVE_THUMB;
        imgEl.style.cursor = "pointer";
        imgEl.title = window.t(isCapture ? "playlist.preview_device_title" : "playlist.preview_live_title");
        imgEl.addEventListener("click", e => {
          e.stopPropagation();
          if (isCapture) {
            if (typeof openCapturePreview === "function") openCapturePreview(item.path, imgEl);
          } else {
            if (typeof openYtPreview === "function") openYtPreview(item.path, imgEl);
          }
        });
      } else if (item.type === "youtube_live") {
        imgEl.src = _YT_THUMB;
        imgEl.style.cursor = "pointer";
        imgEl.title = window.t("playlist.preview_video_title");
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
  _updateErrorCount();
  if (typeof window._onScheduleChangedForInputQuadrant === "function") window._onScheduleChangedForInputQuadrant();
}

function _updateErrorCount() {
  const n = state.schedule.filter(it => it.path && invalidPaths.has(it.path)).length;
  const el = document.getElementById("sch-error-count");
  if (!el) return;
  el.textContent = n === 1 ? window.t("playlist.error_count_one") : `${n} ${window.t("playlist.error_count_many")}`;
  el.style.display = n > 0 ? "inline-flex" : "none";
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
      if (state.playing && i === state.currentIndex) { e.preventDefault(); return; }
      document.querySelectorAll(".schedule-item.editing").forEach(r => r.classList.remove("editing"));
      dragSrcIdx = i;
      e.dataTransfer.effectAllowed = "move";
      window._schedDragging = true;
      setTimeout(() => row.classList.add("dragging"), 0);
    });
    row.addEventListener("dragend", () => {
      // Zera o índice aqui, e não só no drop: um arraste abortado (Esc, solto
      // fora da lista) deixava dragSrcIdx com o índice velho, e um drop
      // posterior vindo de fora do app (arquivo do Explorer) caía na
      // reordenação movendo o item errado. dragend dispara depois do drop,
      // então a reordenação legítima continua funcionando.
      dragSrcIdx = null;
      window._schedDragging = false;
      row.classList.remove("dragging");
      list.querySelector(".drop-indicator")?.remove();
    });
  });
}


// ── Categoria do clipe (pasta da biblioteca) ─────────────────────────────────
// Derivada do caminho, sem estado no servidor: 3 primeiras letras da pasta em
// que o arquivo está (Comerciais -> COM, Documentários -> DOC). Arquivo na raiz
// da biblioteca fica sem categoria; YouTube -> YT; dispositivo de captura -> CAM.

function _normPath(p) {
  return String(p || "").replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
}

function _clipCategory(item) {
  if (item.type === "capture") return { code: "CAM", name: "Dispositivo de captura" };
  if (item.type === "youtube_live") return { code: "YT", name: "YouTube" };
  const p = String(item.path || "");
  if (!p || /^(https?:|av:)/i.test(p)) return null;
  const sep = Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"));
  if (sep <= 0) return null;
  const dir = p.slice(0, sep);
  const base = window._libraryBase || "";
  if (base && _normPath(dir) === _normPath(base)) return null;   // raiz da biblioteca
  const folder = dir.slice(Math.max(dir.lastIndexOf("\\"), dir.lastIndexOf("/")) + 1);
  if (!folder || /^[A-Za-z]:$/.test(folder)) return null;
  const code = folder.normalize("NFD").replace(/\p{M}/gu, "").replace(/[^A-Za-z0-9]/g, "")
    .slice(0, 3).toUpperCase();
  return code ? { code, name: folder } : null;
}

// Cor estável por pasta (hash do nome), só para distinguir categorias no roteiro
function _catHue(name) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h % 360;
}

function _clipCategoryHtml(item) {
  const cat = _clipCategory(item);
  if (!cat) return '<span class="item-cat"></span>';
  const hue = _catHue(cat.name);
  const style = `color:hsl(${hue} 70% 70%);border-color:hsl(${hue} 55% 45% / .55);background:hsl(${hue} 60% 50% / .12)`;
  return `<span class="item-cat" style="${style}" title="${window.t("uimsg.category_folder_title", { name: esc(cat.name) })}">${esc(cat.code)}</span>`;
}

// ── Transição entre clipes ───────────────────────────────────────────────────
// Global: botão no cabeçalho do roteiro (state.transition, vindo do servidor).
// Por clipe: item.transition = "fade" | "cut" | ausente (segue o global).

// Nomenclatura de switcher/automação de broadcast: CUT = corte seco, FTB = fade to black
const _TRANSITION_LABELS = { cut: "CUT", fade: "FTB" };
const _TRANSITION_ITEM_LABELS = { fade: "FTB", cut: "CUT" };

function updateTransitionButton() {
  const btn = document.getElementById("btn-transition");
  if (!btn) return;
  const t = state.transition || { type: "cut", duration: 0.5 };
  btn.dataset.type = t.type;
  btn.textContent = _TRANSITION_LABELS[t.type] || t.type;
  btn.title = t.type === "fade"
    ? window.t("playlist.header_transition_ftb_title", { s: t.duration })
    : window.t("playlist.header_transition_cut_title");
}

document.getElementById("btn-transition")?.addEventListener("click", () => {
  const cur = state.transition?.type || "cut";
  send({ action: "set_transition", type: cur === "fade" ? "cut" : "fade" });
});

function _transitionTagHtml(item) {
  const t = item.transition;
  if (t !== "fade" && t !== "cut") return "";
  return `<span class="item-transition-tag ${t}" title="${window.t("playlist.item_transition_tag_title")}">${_TRANSITION_ITEM_LABELS[t]}</span>`;
}

function _markRowTransition(idx, value) {
  const row = document.querySelector(`.schedule-item[data-index="${idx}"] .item-title-row`);
  if (!row) return;
  row.querySelector(".item-transition-tag")?.remove();
  if (value) row.insertAdjacentHTML("beforeend", _transitionTagHtml({ transition: value }));
}
