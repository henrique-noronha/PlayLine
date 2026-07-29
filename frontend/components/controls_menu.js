/* PlayLine — Menu dropdown de opções do painel de controle */

(function () {
  const wrap    = document.getElementById("controls-menu-wrap");
  const btnOpen = document.getElementById("btn-controls-menu");
  const dropdown = document.getElementById("controls-menu-dropdown");
  const itemMpv  = document.getElementById("ctrl-menu-quit-mpv");

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
    const alive   = state.mpvAlive !== false;
    const playing = state.playing;

    if (alive) {
      itemMpv.textContent = "⏻ Encerrar player MPV";
      itemMpv.classList.toggle("ctrl-menu-item--disabled", playing);
      itemMpv.title = playing ? "Pare a reprodução antes de encerrar o player" : "";
    } else {
      itemMpv.textContent = "⏻ Inicializar player MPV";
      itemMpv.classList.remove("ctrl-menu-item--disabled");
      itemMpv.title = "";
    }

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

  itemMpv.addEventListener("click", async () => {
    if (itemMpv.classList.contains("ctrl-menu-item--disabled")) return;
    const alive = state.mpvAlive !== false;
    closeDropdown();

    if (alive) {
      showConfirm(
        "Encerrar o player MPV? A janela de saída no monitor será fechada.",
        async () => {
          try {
            const res = await fetch("/api/mpv/quit", { method: "POST" });
            if (!res.ok) {
              const err = await res.json().catch(() => ({}));
              log("Erro ao encerrar MPV: " + (err.detail || `HTTP ${res.status}`), "error");
            }
          } catch (err) {
            log("Erro ao encerrar MPV: " + err.message, "error");
          }
        }
      );
    } else {
      try {
        const res = await fetch("/api/mpv/init", { method: "POST" });
        if (res.ok) {
          log("Player MPV inicializado", "info");
        } else {
          const err = await res.json().catch(() => ({}));
          log("Erro ao inicializar MPV: " + (err.detail || `HTTP ${res.status}`), "error");
        }
      } catch (err) {
        log("Erro ao inicializar MPV: " + err.message, "error");
      }
    }
  });
})();
