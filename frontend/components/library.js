/* PlayLine — Biblioteca de vídeos */

let selectedLibPaths = new Set();
let currentLibFiles  = [];

function updateLibSelectionUI() {
  const bar = document.getElementById("lib-sel-bar");
  if (!bar) return;
  if (selectedLibPaths.size > 0) {
    bar.style.display = "flex";
    document.getElementById("lib-sel-count").textContent =
      `${selectedLibPaths.size} selecionado${selectedLibPaths.size !== 1 ? "s" : ""}`;
  } else {
    bar.style.display = "none";
  }
}

async function loadLibrary(folder) {
  const list = document.getElementById("library-list");
  list.innerHTML = '<div class="empty">Carregando…</div>';
  try {
    const res = await fetch("/api/library?folder=" + encodeURIComponent(folder));
    if (!res.ok) { list.innerHTML = '<div class="empty">Pasta não encontrada</div>'; return; }
    const data = await res.json();
    if (!data.files.length) { list.innerHTML = '<div class="empty">Nenhum vídeo encontrado</div>'; return; }

    selectedLibPaths.clear();
    currentLibFiles = data.files;

    let selBar = document.getElementById("lib-sel-bar");
    if (!selBar) {
      selBar = document.createElement("div");
      selBar.id = "lib-sel-bar";
      selBar.className = "lib-sel-bar";
      selBar.style.display = "none";
      selBar.innerHTML = `<span id="lib-sel-count"></span><button id="btn-add-selected">Adicionar ao roteiro</button>`;
      list.parentNode.insertBefore(selBar, list);
      document.getElementById("btn-add-selected").addEventListener("click", () => {
        const toAdd = currentLibFiles.filter(f => selectedLibPaths.has(f.path));
        const now = Date.now();
        toAdd.forEach((f, i) => {
          state.schedule.push({
            id: `item-${now + i}`,
            title: f.name,
            path: f.path,
            duration: 0
          });
        });
        renderSchedule();
        syncOrderToServer();
        selectedLibPaths.clear();
        document.querySelectorAll(".lib-item.selected").forEach(el => el.classList.remove("selected"));
        updateLibSelectionUI();
      });
    }
    updateLibSelectionUI();

    list.innerHTML = "";
    data.files.forEach(file => {
      const item = document.createElement("div");
      item.className = "lib-item";
      item.setAttribute("draggable", "true");
      item.innerHTML = `<img class="lib-thumb" draggable="false" src="" alt="" /><span class="lib-name" title="${esc(file.filename)}">${esc(file.name)}</span><span class="lib-dur">—</span>`;
      list.appendChild(item);

      generateThumb(file.path, item.querySelector(".lib-thumb"), -1);

      const durSpan = item.querySelector(".lib-dur");
      const dv = document.createElement("video");
      dv.muted = true; dv.preload = "metadata";
      dv.src = "/media?path=" + encodeURIComponent(file.path);
      dv.addEventListener("loadedmetadata", () => { durSpan.textContent = fmt(Math.round(dv.duration)); dv.src = ""; });
      dv.addEventListener("error", () => { dv.src = ""; });

      item.addEventListener("click", e => {
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          if (selectedLibPaths.has(file.path)) {
            selectedLibPaths.delete(file.path);
            item.classList.remove("selected");
          } else {
            selectedLibPaths.add(file.path);
            item.classList.add("selected");
          }
          updateLibSelectionUI();
        }
      });

      item.addEventListener("dragstart", e => {
        libDragFile = file;
        dragSrcIdx = null;
        e.dataTransfer.effectAllowed = "all";
        e.dataTransfer.setData("library-file", JSON.stringify(file));
        setTimeout(() => item.classList.add("dragging"), 0);
      });
      item.addEventListener("dragend", () => item.classList.remove("dragging"));
    });
  } catch (err) {
    list.innerHTML = `<div class="empty">Erro: ${esc(err.message)}</div>`;
  }
}

document.getElementById("btn-load-library").addEventListener("click", () => {
  const folder = document.getElementById("library-folder-input").value.trim();
  if (!folder) return;
  localStorage.setItem("playline_library_folder", folder);
  loadLibrary(folder);
});

document.getElementById("library-folder-input").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("btn-load-library").click();
});
