/* PlayLine — Menu dropdown de opções do painel de controle */

(function () {
  const wrap    = document.getElementById("controls-menu-wrap");
  const btnOpen = document.getElementById("btn-controls-menu");
  const dropdown = document.getElementById("controls-menu-dropdown");
  // ── Zoom ──────────────────────────────────────────────────────────────
  const ZOOM_STEPS = [70, 80, 90, 100, 110, 120, 130, 150];
  let _zoom = parseInt(localStorage.getItem('pl-zoom') || '100', 10);
  if (!ZOOM_STEPS.includes(_zoom)) _zoom = 100;

  function _applyZoom(z) {
    _zoom = z;
    document.body.style.zoom = _zoom + '%';
    localStorage.setItem('pl-zoom', String(_zoom));
  }

  _applyZoom(_zoom);

  const btnZoomIn     = document.getElementById("ctrl-menu-zoom-in");
  const btnZoomOut    = document.getElementById("ctrl-menu-zoom-out");
  const itemZoomReset = document.getElementById("ctrl-menu-zoom-reset");
  const zoomVal       = document.getElementById("ctrl-menu-zoom-val");

  btnZoomIn.addEventListener("click", e => {
    e.stopPropagation();
    const idx = ZOOM_STEPS.indexOf(_zoom);
    if (idx < ZOOM_STEPS.length - 1) _applyZoom(ZOOM_STEPS[idx + 1]);
    _updateItem();
  });

  btnZoomOut.addEventListener("click", e => {
    e.stopPropagation();
    const idx = ZOOM_STEPS.indexOf(_zoom);
    if (idx > 0) _applyZoom(ZOOM_STEPS[idx - 1]);
    _updateItem();
  });

  itemZoomReset.addEventListener("click", () => {
    _applyZoom(100);
    _updateItem();
    closeDropdown();
  });

  // ──────────────────────────────────────────────────────────────────────

  function _updateItem() {
    const idx = ZOOM_STEPS.indexOf(_zoom);
    btnZoomIn.disabled  = idx >= ZOOM_STEPS.length - 1;
    btnZoomOut.disabled = idx <= 0;
    zoomVal.textContent = _zoom + "%";
    itemZoomReset.classList.toggle("ctrl-menu-item--disabled", _zoom === 100);
  }

  function openDropdown() {
    _updateItem();
    dropdown.classList.add("open");
  }

  function closeDropdown() {
    dropdown.classList.remove("open");
  }

  btnOpen.addEventListener("click", e => {
    e.stopPropagation();
    dropdown.classList.contains("open") ? closeDropdown() : openDropdown();
  });

  document.addEventListener("click", e => {
    if (!wrap.contains(e.target)) closeDropdown();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeDropdown();
  });

  document.getElementById("ctrl-menu-history").addEventListener("click", () => {
    closeDropdown();
    openHistoryModal();
  });

})();
