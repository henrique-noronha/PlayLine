/* PlayLine — Biblioteca de vídeos com subpastas */

let selectedLibPaths  = new Set();
let currentLibFiles   = [];
let _libCurrentFolder = "";
let _libSearchQuery   = "";

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
  _updateLibMenuState();
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
    _updateLibMenuState();
    loadLibraryFiles(folder);
  });
  return btn;
}

function _toggleNewFolderForm() {
  let form = document.getElementById("lib-new-folder-form");
  if (form) { form.remove(); return; }

  form = document.createElement("div");
  form.id = "lib-new-folder-form";
  form.className = "lib-new-folder-form";
  form.innerHTML = `
    <input id="lib-new-folder-input" class="lib-new-folder-input" type="text" placeholder="Nome da pasta" maxlength="40" />
    <button id="lib-new-folder-ok" class="lib-new-folder-ok" title="Criar">✓</button>
    <button id="lib-new-folder-cancel" class="lib-new-folder-cancel" title="Cancelar">✕</button>
  `;

  const container = document.getElementById("lib-folders").parentElement;
  document.getElementById("lib-folders").after(form);

  const inp = form.querySelector("#lib-new-folder-input");
  inp.focus();

  form.querySelector("#lib-new-folder-cancel").addEventListener("click", () => form.remove());
  form.querySelector("#lib-new-folder-ok").addEventListener("click",    () => _createFolder(inp.value));
  inp.addEventListener("keydown", e => {
    if (e.key === "Enter")  _createFolder(inp.value);
    if (e.key === "Escape") form.remove();
  });
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
    _updateLibMenuState();
    loadLibraryFiles(name);
  } catch (err) {
    log(`Erro ao criar pasta: ${err.message}`, "error");
  }
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
    _updateLibMenuState();

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
      item.innerHTML = `<img class="lib-thumb" draggable="false" src="" alt="" /><span class="lib-name" title="${esc(file.filename)}">${esc(file.name)}</span><span class="lib-dur">—</span>`;
      list.appendChild(item);

      generateThumb(file.path, item.querySelector(".lib-thumb"));

      const durSpan = item.querySelector(".lib-dur");
      const dv = document.createElement("video");
      dv.muted = true; dv.preload = "metadata";
      dv.addEventListener("loadedmetadata", () => { durSpan.textContent = fmt(Math.round(dv.duration)); dv.src = ""; }, { once: true });
      dv.addEventListener("error",          () => { dv.src = ""; }, { once: true });
      dv.src = "/media?path=" + encodeURIComponent(file.path);

      item.addEventListener("click", e => {
        if (!(e.ctrlKey || e.metaKey)) return;
        e.preventDefault();
        if (selectedLibPaths.has(file.path)) {
          selectedLibPaths.delete(file.path);
          item.classList.remove("selected");
        } else {
          selectedLibPaths.add(file.path);
          item.classList.add("selected");
        }
        _updateLibSelectionUI();
      });

      item.addEventListener("dragstart", e => {
        libDragFile = file;
        dragSrcIdx  = null;
        e.dataTransfer.effectAllowed = "all";
        e.dataTransfer.setData("library-file", JSON.stringify(file));
        setTimeout(() => item.classList.add("dragging"), 0);
      });
      item.addEventListener("dragend", () => item.classList.remove("dragging"));
    });

    _applyLibSearch();
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

// ── Menu ··· da biblioteca ────────────────────────────────────────────────────

function _updateLibMenuState() {
  const isSub = _libCurrentFolder !== "";
  document.getElementById("lib-menu-rename-folder")?.classList.toggle("disabled", !isSub);
  const canRemove = isSub && currentLibFiles.length === 0;
  document.getElementById("lib-menu-remove-folder")?.classList.toggle("disabled", !canRemove);
}

function _closeLibMenu() {
  document.getElementById("lib-menu-dropdown")?.classList.remove("open");
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

document.getElementById("btn-lib-menu")?.addEventListener("click", e => {
  e.stopPropagation();
  document.getElementById("lib-menu-dropdown")?.classList.toggle("open");
});

document.addEventListener("click", _closeLibMenu);

document.getElementById("lib-menu-new-folder")?.addEventListener("click", () => {
  _closeLibMenu();
  _toggleNewFolderForm();
});

document.getElementById("lib-menu-rename-folder")?.addEventListener("click", () => {
  _closeLibMenu();
  if (_libCurrentFolder) _showRenameFolderForm(_libCurrentFolder);
});

document.getElementById("lib-menu-remove-folder")?.addEventListener("click", () => {
  _closeLibMenu();
  if (_libCurrentFolder) _confirmRemoveFolder(_libCurrentFolder);
});

function _showRenameFolderForm(currentName) {
  document.getElementById("lib-new-folder-form")?.remove();

  const form = document.createElement("div");
  form.id = "lib-new-folder-form";
  form.className = "lib-new-folder-form";
  form.innerHTML = `
    <input id="lib-new-folder-input" class="lib-new-folder-input" type="text" placeholder="Novo nome" maxlength="40" value="${esc(currentName)}" />
    <button id="lib-new-folder-ok" class="lib-new-folder-ok" title="Renomear">✓</button>
    <button id="lib-new-folder-cancel" class="lib-new-folder-cancel" title="Cancelar">✕</button>
  `;

  document.getElementById("lib-folders").after(form);
  const inp = form.querySelector("#lib-new-folder-input");
  inp.focus();
  inp.select();

  form.querySelector("#lib-new-folder-cancel").addEventListener("click", () => form.remove());
  form.querySelector("#lib-new-folder-ok").addEventListener("click", () => _renameFolder(currentName, inp.value));
  inp.addEventListener("keydown", e => {
    if (e.key === "Enter")  _renameFolder(currentName, inp.value);
    if (e.key === "Escape") form.remove();
  });
}

async function _renameFolder(oldName, newName) {
  newName = newName.trim();
  if (!newName || newName === oldName) { document.getElementById("lib-new-folder-form")?.remove(); return; }
  try {
    const res = await fetch("/api/library/folder", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old: oldName, new: newName }),
    });
    if (!res.ok) {
      const err = await res.json();
      log(`Erro ao renomear pasta: ${err.detail}`, "error");
      return;
    }
    document.getElementById("lib-new-folder-form")?.remove();
    _libCurrentFolder = newName;
    await loadLibraryFolders();
    document.querySelectorAll(".lib-folder-tab").forEach(b => {
      b.classList.toggle("active", b.dataset.folder === newName);
    });
    loadLibraryFiles(newName);
  } catch (err) {
    log(`Erro ao renomear pasta: ${err.message}`, "error");
  }
}

async function _confirmRemoveFolder(name) {
  showConfirm(`Remover a pasta "${name}"? (Ela precisa estar vazia.)`, async () => {
    try {
      const res = await fetch(`/api/library/folder?subfolder=${encodeURIComponent(name)}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json();
        log(`Erro ao remover pasta: ${err.detail}`, "error");
        return;
      }
      _libCurrentFolder = "";
      await loadLibraryFolders();
    } catch (err) {
      log(`Erro ao remover pasta: ${err.message}`, "error");
    }
  });
}
