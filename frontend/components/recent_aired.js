/* ── Últimos exibidos (as-run) no quadrante de entrada ──
   Lê /api/history (mesma fonte do modal de histórico). Não faz polling: app.js
   chama refresh() em state/now_playing/stopped/playlist_end, que é quando o
   servidor acabou de fechar uma entrada do histórico. */

(function () {
  const LIMIT = 15;

  // Mesmos códigos de end_reason do backend (core/history.py)
  const _REASON_KEYS = {
    completed: "historymodal.reason_completed",
    stopped: "historymodal.reason_stopped",
    skipped: "historymodal.reason_skipped",
    interrupted: "historymodal.reason_interrupted",
    error: "historymodal.reason_error",
  };

  let _entries = [];
  let _timer = null;
  let _seq = 0;

  // Data local (o servidor grava com datetime.now(), não UTC)
  function _todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function _fmtDuration(secs) {
    secs = Math.max(0, Math.round(secs || 0));
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    const mm = String(m).padStart(2, "0");
    const ss = String(s).padStart(2, "0");
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }

  function _fmtDate(iso) {
    const [y, m, d] = (iso || "").split("-");
    return d ? `${d}/${m}/${y}` : "";
  }

  function _render() {
    const list = document.getElementById("ra-list");
    const empty = document.getElementById("ra-empty");
    if (!list) return;

    list.textContent = "";
    empty.style.display = _entries.length ? "none" : "";

    const today = _todayStr();
    for (const e of _entries) {
      const li = document.createElement("li");
      li.className = "ra-item";
      li.dataset.reason = e.end_reason || "";
      if (e.date !== today) li.classList.add("ra-old");

      const key = _REASON_KEYS[e.end_reason];
      li.title = window.t("recentaired.tooltip", {
        date: _fmtDate(e.date),
        start: e.started_at || "",
        end: e.ended_at || "",
        reason: key ? window.t(key) : (e.end_reason_label || e.end_reason || ""),
      }) + "\n" + (e.path || "");

      const time = document.createElement("span");
      time.className = "ra-time";
      time.textContent = e.started_at || "";

      const title = document.createElement("span");
      title.className = "ra-title";
      title.textContent = e.title || "";

      const dur = document.createElement("span");
      dur.className = "ra-dur";
      dur.textContent = _fmtDuration(e.duration_played);

      li.append(time, title, dur);
      list.appendChild(li);
    }
  }

  async function _load() {
    const seq = ++_seq;
    try {
      const res = await fetch(`/api/history?limit=${LIMIT}`);
      if (!res.ok) return;
      const { entries } = await res.json();
      if (seq !== _seq) return; // resposta de uma requisição mais antiga
      _entries = entries || [];
      _render();
    } catch (_) {
      // Mantém a última lista; o próximo evento tenta de novo
    }
  }

  // Agrupa eventos em sequência (ex.: stopped + state na reconexão)
  function refresh() {
    clearTimeout(_timer);
    _timer = setTimeout(_load, 250);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("ra-see-all")?.addEventListener("click", () => window.openHistoryModal?.());
    refresh();
  });
  document.addEventListener("playline:lang-applied", _render);

  window._recentAired = { refresh };
})();
