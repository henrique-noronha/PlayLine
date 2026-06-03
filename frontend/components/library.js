/* PlayLine — Biblioteca de vídeos */

async function loadLibrary(folder) {
  const list = document.getElementById("library-list");
  list.innerHTML = '<div class="empty">Carregando…</div>';
  try {
    const res = await fetch("/api/library?folder=" + encodeURIComponent(folder));
    if (!res.ok) { list.innerHTML = '<div class="empty">Pasta não encontrada</div>'; return; }
    const data = await res.json();
    if (!data.files.length) { list.innerHTML = '<div class="empty">Nenhum vídeo encontrado</div>'; return; }
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
