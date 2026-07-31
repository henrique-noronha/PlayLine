/* PlayLine — Biblioteca de vídeos com subpastas */

let selectedLibPaths  = new Set();
let currentLibFiles   = [];
let _libCurrentFolder = "";
let _libSearchQuery   = "";

const _isTouch = window.matchMedia("(pointer: coarse)").matches;

const _AUDIO_EXTS = new Set([".mp3", ".wav", ".aac", ".m4a"]);
function _isAudio(path) {
  const ext = path.slice(path.lastIndexOf(".")).toLowerCase();
  return _AUDIO_EXTS.has(ext);
}

// ── Abas de subpastas ────────────────────────────────────────────────────────

async function loadLibraryFolders() {
  try {
    const res  = await fetch("/api/library");
    const data = await res.json();
    _renderFolderTabs(data.subfolders || []);
    loadLibraryFiles(_libCurrentFolder);
  } catch (err) {
    document.getElementById("library-list").innerHTML =
      `<div class="empty">Erro ao carregar biblioteca: ${esc(err.message)}</div>`;
  }
}

function _renderFolderTabs(subfolders) {
  const el = document.getElementById("lib-folders");
  if (!el) return;
  el.innerHTML = "";

  // Se a pasta atual foi deletada, volta para Todos
  if (_libCurrentFolder && !subfolders.includes(_libCurrentFolder)) {
    _libCurrentFolder = "";
  }

  el.appendChild(_makeTab("Todos", ""));
  subfolders.forEach(sf => el.appendChild(_makeTab(sf, sf)));

}

function _makeTab(label, folder) {
  const btn = document.createElement("button");
  btn.className = "lib-folder-tab" + (_libCurrentFolder === folder ? " active" : "");
  btn.textContent = label;
  btn.dataset.folder = folder;
  btn.addEventListener("click", () => {
    _libCurrentFolder = folder;
    _libSearchQuery = "";
    const si = document.getElementById("lib-search-input");
    if (si) si.value = "";
    document.querySelectorAll(".lib-folder-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
  
    loadLibraryFiles(folder);
  });
  return btn;
}


async function _createFolder(name) {
  name = name.trim();
  if (!name) return;
  try {
    const res = await fetch("/api/library/folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) {
      const err = await res.json();
      log(`Erro ao criar pasta: ${err.detail}`, "error");
      return;
    }
    document.getElementById("lib-new-folder-form")?.remove();
    await loadLibraryFolders();
    _libCurrentFolder = name;
    document.querySelectorAll(".lib-folder-tab").forEach(b => {
      b.classList.toggle("active", b.dataset.folder === name);
    });
  
    loadLibraryFiles(name);
  } catch (err) {
    log(`Erro ao criar pasta: ${err.message}`, "error");
  }
}

// ── Ghost de drag para seleção múltipla ──────────────────────────────────────

function _setMultiDragImage(e, sourceItem, count) {
  const W = 80, H = 60;
  const ghost = document.createElement("div");
  ghost.style.cssText = "position:fixed;top:-9999px;left:-9999px;pointer-events:none;";

  const wrap = document.createElement("div");
  wrap.style.cssText = `position:relative;width:${W + 8}px;height:${H + 8}px;`;

  // Cartas empilhadas atrás
  [{t:8,l:8,o:0.40},{t:4,l:4,o:0.65}].forEach(({t,l,o}) => {
    const s = document.createElement("div");
    s.style.cssText = `position:absolute;top:${t}px;left:${l}px;width:${W}px;height:${H}px;`
      + `background:#4a4a5a;border-radius:7px;opacity:${o};`;
    wrap.appendChild(s);
  });

  // Carta principal com thumbnail
  const card = document.createElement("div");
  card.style.cssText = `position:absolute;top:0;left:0;width:${W}px;height:${H}px;`
    + `border-radius:7px;overflow:hidden;background:#1e1e2a;border:1.5px solid rgba(255,255,255,0.18);box-sizing:border-box;`;
  const thumb = sourceItem.querySelector(".lib-thumb");
  if (thumb && thumb.src && thumb.naturalWidth > 0) {
    const img = document.createElement("img");
    img.src = thumb.src;
    img.style.cssText = "width:100%;height:100%;object-fit:cover;display:block;";
    card.appendChild(img);
  }
  wrap.appendChild(card);

  // Badge com contagem
  const badge = document.createElement("div");
  badge.textContent = count;
  badge.style.cssText = `position:absolute;top:-9px;left:${W - 14}px;min-width:22px;height:22px;padding:0 5px;`
    + `background:#4a9eff;color:#fff;border-radius:11px;display:flex;align-items:center;`
    + `justify-content:center;font-size:12px;font-weight:700;line-height:1;box-sizing:border-box;`;
  wrap.appendChild(badge);

  ghost.appendChild(wrap);
  document.body.appendChild(ghost);
  e.dataTransfer.setDragImage(wrap, W / 2, H / 2);
  setTimeout(() => ghost.remove(), 0);
}

// ── Arquivos ─────────────────────────────────────────────────────────────────

async function loadLibraryFiles(subfolder) {
  const list = document.getElementById("library-list");
  list.innerHTML = '<div class="empty">Carregando…</div>';
  try {
    const url = subfolder
      ? `/api/library/files?subfolder=${encodeURIComponent(subfolder)}`
      : "/api/library/files";
    const res  = await fetch(url);
    if (!res.ok) { list.innerHTML = '<div class="empty">Pasta não encontrada</div>'; return; }
    const data = await res.json();

    selectedLibPaths.clear();
    currentLibFiles = data.files;
  

    // Limpar erro de caminhos que voltaram a existir na biblioteca
    let anyRestored = false;
    currentLibFiles.forEach(f => { if (window._clearPathError?.(f.path)) anyRestored = true; });
    if (anyRestored && typeof renderSchedule === "function") renderSchedule();

    if (!data.files.length) {
      list.innerHTML = subfolder
        ? '<div class="empty">Nenhum vídeo nesta pasta</div>'
        : '<div class="empty">Cole vídeos na pasta Biblioteca para começar</div>';
      _updateLibSelectionUI();
      return;
    }

    _ensureSelBar(list);
    _updateLibSelectionUI();

    list.innerHTML = "";
    data.files.forEach(file => {
      const item = document.createElement("div");
      item.className = "lib-item";
      item.setAttribute("draggable", "true");
      const audio = _isAudio(file.path);
      item.innerHTML = audio
        ? `<div class="lib-thumb-wrap"><div class="lib-audio-thumb">♪</div><span class="lib-sched-badge" data-path="${esc(file.path)}"></span></div><span class="lib-audio-badge">áudio</span><span class="lib-name" title="${esc(file.filename)}">${esc(file.name)}</span><span class="lib-dur">—</span><button class="lib-add-btn" title="Adicionar ao roteiro">+</button>`
        : `<div class="lib-thumb-wrap"><img class="lib-thumb" draggable="false" src="" alt="" /><span class="lib-sched-badge" data-path="${esc(file.path)}"></span></div><span class="lib-name" title="${esc(file.filename)}">${esc(file.name)}</span><span class="lib-dur">—</span><button class="lib-add-btn" title="Adicionar ao roteiro">+</button>`;
      list.appendChild(item);

      if (!audio) generateThumb(file.path, item.querySelector(".lib-thumb"));

      const durSpan = item.querySelector(".lib-dur");
      const dv = document.createElement("video");
      dv.muted = true; dv.preload = "metadata";
      dv.addEventListener("loadedmetadata", () => { durSpan.textContent = fmt(Math.round(dv.duration)); dv.src = ""; }, { once: true });
      dv.addEventListener("error", () => { dv.src = ""; }, { once: true });
      dv.src = "/media?path=" + encodeURIComponent(file.path);

      // Botão "+" — adiciona direto ao roteiro (visível só em touch via CSS)
      item.querySelector(".lib-add-btn").addEventListener("click", e => {
        e.stopPropagation();
        const now = Date.now();
        state.schedule.push({ id: `item-${now}`, title: file.name, path: file.path, duration: 0 });
        renderSchedule();
        syncOrderToServer();
        item.classList.add("lib-added");
        setTimeout(() => item.classList.remove("lib-added"), 700);
        if (audio) showToast("♪ Arquivo de áudio — sem imagem no roteiro", "warn");
      });

      item.addEventListener("click", e => {
        if (_isTouch) {
          // Touch: toque simples alterna seleção (sem precisar de Ctrl)
          if (selectedLibPaths.has(file.path)) {
            selectedLibPaths.delete(file.path);
            item.classList.remove("selected");
          } else {
            selectedLibPaths.add(file.path);
            item.classList.add("selected");
          }
          _updateLibSelectionUI();
        } else {
          // Desktop: Ctrl/Meta alterna; clique simples limpa seleção
          if (!(e.ctrlKey || e.metaKey)) {
            if (selectedLibPaths.size > 0) {
              selectedLibPaths.clear();
              document.querySelectorAll(".lib-item.selected").forEach(el => el.classList.remove("selected"));
              _updateLibSelectionUI();
            }
            return;
          }
          e.preventDefault();
          if (selectedLibPaths.has(file.path)) {
            selectedLibPaths.delete(file.path);
            item.classList.remove("selected");
          } else {
            selectedLibPaths.add(file.path);
            item.classList.add("selected");
          }
          _updateLibSelectionUI();
        }
      });

      item.addEventListener("dragstart", e => {
        libDragFile = file;
        dragSrcIdx  = null;
        e.dataTransfer.effectAllowed = "all";
        e.dataTransfer.setData("library-file", JSON.stringify(file));
        if (selectedLibPaths.size > 1 && selectedLibPaths.has(file.path)) {
          const multiFiles = currentLibFiles.filter(f => selectedLibPaths.has(f.path));
          e.dataTransfer.setData("library-files-multi", JSON.stringify(multiFiles));
          _setMultiDragImage(e, item, multiFiles.length);
          setTimeout(() => {
            document.querySelectorAll(".lib-item.selected").forEach(el => el.classList.add("dragging"));
          }, 0);
        } else {
          setTimeout(() => item.classList.add("dragging"), 0);
        }
      });
      item.addEventListener("dragend", () => {
        document.querySelectorAll(".lib-item.dragging").forEach(el => el.classList.remove("dragging"));
      });
    });

    _applyLibSearch();
    window._refreshLibSchedBadges?.();
  } catch (err) {
    list.innerHTML = `<div class="empty">Erro: ${esc(err.message)}</div>`;
  }
}

function _applyLibSearch() {
  const q = _libSearchQuery;
  document.querySelectorAll("#library-list .lib-item").forEach(item => {
    const name = (item.querySelector(".lib-name")?.textContent || "").toLowerCase();
    item.style.display = (!q || name.includes(q)) ? "" : "none";
  });
}

// ── Barra de seleção ──────────────────────────────────────────────────────────

function _ensureSelBar(list) {
  if (document.getElementById("lib-sel-bar")) return;
  const selBar = document.createElement("div");
  selBar.id = "lib-sel-bar";
  selBar.className = "lib-sel-bar";
  selBar.style.display = "none";
  selBar.innerHTML = `<span id="lib-sel-count"></span><button id="btn-add-selected">Adicionar ao roteiro</button>`;
  list.parentNode.insertBefore(selBar, list);

  document.getElementById("btn-add-selected").addEventListener("click", () => {
    const toAdd = currentLibFiles.filter(f => selectedLibPaths.has(f.path));
    const now   = Date.now();
    toAdd.forEach((f, i) => {
      state.schedule.push({ id: `item-${now + i}`, title: f.name, path: f.path, duration: 0 });
    });
    renderSchedule();
    syncOrderToServer();
    const audioCount = toAdd.filter(f => _isAudio(f.path)).length;
    if (audioCount > 0) showToast(`♪ ${audioCount} arquivo${audioCount > 1 ? "s" : ""} de áudio adicionado${audioCount > 1 ? "s" : ""} — sem imagem no roteiro`, "warn");
    selectedLibPaths.clear();
    document.querySelectorAll(".lib-item.selected").forEach(el => el.classList.remove("selected"));
    _updateLibSelectionUI();
  });
}

function updateLibSelectionUI() { _updateLibSelectionUI(); }

function _updateLibSelectionUI() {
  const bar = document.getElementById("lib-sel-bar");
  if (!bar) return;
  if (currentLibFiles.length > 0) {
    bar.style.display = "flex";
    const n = selectedLibPaths.size;
    document.getElementById("lib-sel-count").textContent =
      n > 0 ? `${n} selecionado${n !== 1 ? "s" : ""}` : "";
    const btnAdd = document.getElementById("btn-add-selected");
    if (btnAdd) btnAdd.style.display = n > 0 ? "" : "none";
  } else {
    bar.style.display = "none";
  }
}

document.getElementById("btn-lib-refresh")?.addEventListener("click", loadLibraryFolders);

document.getElementById("btn-lib-search")?.addEventListener("click", () => {
  const row = document.getElementById("lib-search-row");
  if (!row) return;
  const open = row.classList.toggle("open");
  if (open) {
    document.getElementById("lib-search-input")?.focus();
  } else {
    _libSearchQuery = "";
    const si = document.getElementById("lib-search-input");
    if (si) si.value = "";
    _applyLibSearch();
  }
});

document.getElementById("lib-search-input")?.addEventListener("input", e => {
  _libSearchQuery = e.target.value.toLowerCase().trim();
  _applyLibSearch();
});
