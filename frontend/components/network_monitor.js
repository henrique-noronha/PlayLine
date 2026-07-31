/* PlayLine — Monitor de rede e reconexão de stream */

(function () {
  // ── Estado interno ────────────────────────────────────────────────────────
  let _currentItem     = null;   // item do now_playing atual
  let _reconnecting    = false;  // true enquanto o backend está tentando reconectar
  let _offlineTriggered = false; // popup aberto pelo evento offline do browser
  let _countdownTimer  = null;

  // ── Helpers de DOM ────────────────────────────────────────────────────────
  const _banner       = () => document.getElementById("reconnect-banner");
  const _bannerText   = () => document.getElementById("reconnect-banner-text");
  const _popup        = () => document.getElementById("net-alert-popup");
  const _popupTitle   = () => document.getElementById("net-alert-title");
  const _popupMsg     = () => document.getElementById("net-alert-msg");
  const _popupCountdown = () => document.getElementById("net-alert-countdown");

  function _isStream(item) {
    return item && (item.type === "youtube_live" || (item.path && item.path.startsWith("http")));
  }

  // ── Banner (abaixo do player) ─────────────────────────────────────────────
  function _showBanner(text) {
    const b = _banner();
    if (!b) return;
    _bannerText().textContent = text;
    b.style.display = "flex";
  }

  function _hideBanner() {
    const b = _banner();
    if (b) b.style.display = "none";
  }

  // ── Popup flutuante ───────────────────────────────────────────────────────
  function _showPopup(title, msg) {
    const p = _popup();
    if (!p) return;
    _popupTitle().textContent = title;
    _popupMsg().textContent   = msg;
    p.style.display = "flex";
  }

  function _hidePopup() {
    const p = _popup();
    if (p) p.style.display = "none";
    _clearCountdown();
    _offlineTriggered = false;
  }

  function _startCountdown(totalSecs) {
    _clearCountdown();
    const el = _popupCountdown();
    if (!el) return;
    let remaining = totalSecs;
    function _tick() {
      if (remaining <= 0) {
        el.textContent = "Verificando conexão...";
        _countdownTimer = null;
        return;
      }
      el.textContent = `Próxima tentativa em ${remaining}s`;
      remaining--;
      _countdownTimer = setTimeout(_tick, 1000);
    }
    _tick();
  }

  function _clearCountdown() {
    if (_countdownTimer) { clearTimeout(_countdownTimer); _countdownTimer = null; }
    const el = _popupCountdown();
    if (el) el.textContent = "";
  }

  // ── Eventos do browser (rede do sistema operacional) ─────────────────────
  window.addEventListener("offline", () => {
    if (!_isStream(_currentItem)) return;
    const playing = typeof state !== "undefined" ? state.playing : false;
    if (!playing) return;
    _offlineTriggered = true;
    _showBanner("Sem conexão de rede");
    _showPopup(
      "⚠ Sem conexão de rede",
      "A stream será interrompida. O sistema tentará reconectar automaticamente."
    );
    _clearCountdown();
  });

  window.addEventListener("online", () => {
    if (_offlineTriggered && !_reconnecting) {
      _hideBanner();
      _hidePopup();
    }
  });

  // ── Handlers chamados pelo app.js ─────────────────────────────────────────
  window._netMonitor = {

    onNowPlaying(item) {
      _currentItem  = item;
      _reconnecting = false;
      _hideBanner();
      _hidePopup();
    },

    onStopped() {
      _currentItem  = null;
      _reconnecting = false;
      _hideBanner();
      _hidePopup();
    },

    onReconnecting(ev) {
      _reconnecting = true;
      const attempt    = ev.attempt     || 1;
      const maxAttempts = ev.max_attempts || 2;
      const delaySecs  = Math.round((ev.retry_in_ms || 6000) / 1000);

      _showBanner(`Reconectando... (${attempt}/${maxAttempts})`);
      _showPopup(
        "⚠ Stream interrompida",
        attempt < maxAttempts
          ? `Tentando reconectar (${attempt}/${maxAttempts})...`
          : `Última tentativa de reconexão (${attempt}/${maxAttempts})...`
      );
      _startCountdown(delaySecs);

      // Informa qual clipe virá a seguir se falhar
      const next = _findNextClip();
      const cd = _popupCountdown();
      if (next && cd) {
        // Appended after countdown starts — update on next paint
        setTimeout(() => {
          if (cd && _reconnecting) {
            const existing = cd.textContent;
            cd.textContent = existing; // preserve countdown
          }
        }, 50);
      }
    },

    onReconnectFailed() {
      _reconnecting = false;
      _clearCountdown();
      _showBanner("Reconexão falhou — avançando...");
      const next = _findNextClip();
      _popupTitle().textContent = "⚠ Reconexão falhou";
      _popupMsg().textContent   = next
        ? `Avançando para: "${next.title || "próximo clipe"}"`
        : "Avançando para o próximo clipe do roteiro.";
      _popupCountdown().textContent = "";
      // Auto-hide após o next_playing chegar; fallback de 4s
      setTimeout(() => { if (!_reconnecting) { _hideBanner(); _hidePopup(); } }, 4000);
    },
  };

  // ── Busca o próximo clipe não-live no roteiro ─────────────────────────────
  function _findNextClip() {
    const sched = typeof state !== "undefined" ? (state.schedule || []) : [];
    for (let i = 1; i < sched.length; i++) {
      if (sched[i].path && !sched[i].live) return sched[i];
    }
    return sched[1] || null; // fallback: qualquer próximo
  }

  // ── Botão fechar ──────────────────────────────────────────────────────────
  document.getElementById("net-alert-close")?.addEventListener("click", _hidePopup);
})();
