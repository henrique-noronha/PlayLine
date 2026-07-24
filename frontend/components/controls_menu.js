/* PlayLine — Menu dropdown de opções do painel de controle */

(function () {
  const wrap    = document.getElementById("controls-menu-wrap");
  const btnOpen = document.getElementById("btn-controls-menu");
  const dropdown = document.getElementById("controls-menu-dropdown");
  const itemMpv  = document.getElementById("ctrl-menu-quit-mpv");

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
