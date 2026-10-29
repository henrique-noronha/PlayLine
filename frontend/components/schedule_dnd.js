/* PlayLine — Drop na lista do roteiro + autoscroll de borda durante arraste */

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

  // ── Autoscroll de borda durante o arraste ─────────────────────────────────
  const _EDGE_PX    = 52;
  const _EDGE_SPEED = 900;
  const _EDGE_FLOOR = 0.18;
  const _EDGE_TICK  = 15;
  const _EDGE_IDLE  = 700;

  let _edgeTimer = 0;
  let _edgeY     = 0;
  let _edgeSeen  = 0;
  let _edgeLast  = 0;

  function _edgeRamp(depth) {
    const t = Math.min(1, depth / _EDGE_PX);
    return _EDGE_SPEED * (_EDGE_FLOOR + (1 - _EDGE_FLOOR) * t);
  }

  function _edgeVelocity() {
    const r    = list.getBoundingClientRect();
    const up   = _EDGE_PX - (_edgeY - r.top);
    const down = _EDGE_PX - (r.bottom - _edgeY);
    if (up   > 0) return -_edgeRamp(up);
    if (down > 0) return  _edgeRamp(down);
    return 0;
  }

  function _edgeStep() {
    const now = performance.now();
    if (now - _edgeSeen > _EDGE_IDLE) { _edgeStop(); return; }
    const dt  = Math.min(0.05, (now - _edgeLast) / 1000);
    _edgeLast = now;
    const v = _edgeVelocity();
    if (!v) return;
    const before = list.scrollTop;
    list.scrollTop = before + v * dt;
    if (list.scrollTop === before) return;
    _dropIdx = _calcIdx(_edgeY);
    if (state.playing && _dropIdx <= state.currentIndex) _hideInd();
    else _placeInd(_dropIdx);
  }

  function _edgeStart(clientY) {
    _edgeY    = clientY;
    _edgeSeen = performance.now();
    if (_edgeTimer) return;
    _edgeLast  = _edgeSeen;
    _edgeTimer = setInterval(_edgeStep, _EDGE_TICK);
  }

  function _edgeStop() {
    if (_edgeTimer) clearInterval(_edgeTimer);
    _edgeTimer = 0;
  }

  list.addEventListener("dragover", e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = e.dataTransfer.types.includes("library-file") ? "copy" : "move";
    _edgeStart(e.clientY);
    _dropIdx = _calcIdx(e.clientY);
    if (state.playing && _dropIdx <= state.currentIndex) { _hideInd(); return; }
    _placeInd(_dropIdx);
  });

  list.addEventListener("dragleave", e => {
    if (!list.contains(e.relatedTarget)) { _hideInd(); _edgeStop(); }
  });

  document.addEventListener("dragend", () => { _hideInd(); _edgeStop(); });

  list.addEventListener("drop", e => {
    e.preventDefault();
    _hideInd();
    _edgeStop();
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
      renderSchedule();
      syncOrderToServer();
      return;
    }

    const libRaw = e.dataTransfer.getData("library-file");
    if (libRaw) {
      addFromLibrary(JSON.parse(libRaw), idx);
      return;
    }

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
