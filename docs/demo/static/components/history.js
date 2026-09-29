/* ── Modal de Histórico de Exibição ── */

(function () {
  let _currentDate = "";

  function _todayStr() {
    return new Date().toISOString().slice(0, 10);
  }

  function _fmtDate(iso) {
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
  }

  function _shiftDate(iso, days) {
    const d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function _fmtDuration(secs) {
    if (!secs && secs !== 0) return "—";
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
    if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
    return `${s}s`;
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Aba: Registro ──────────────────────────────────────────────────────

  // O backend manda o codigo bruto em end_reason (completed/stopped/skipped/
  // interrupted/error) alem do end_reason_label ja em portugues — traduzimos
  // pelo codigo, e so caimos pro label do servidor se o codigo nao for
  // reconhecido (compativel com valores futuros sem quebrar a tela).
  const _REASON_KEYS = {
    completed: "historymodal.reason_completed",
    stopped: "historymodal.reason_stopped",
    skipped: "historymodal.reason_skipped",
    interrupted: "historymodal.reason_interrupted",
    error: "historymodal.reason_error",
  };
  function _reasonLabel(e) {
    const key = _REASON_KEYS[e.end_reason];
    return key ? window.t(key) : (e.end_reason_label || e.end_reason || "—");
  }

  async function _load(date) {
    const tbody = document.getElementById("hist-tbody");
    const empty = document.getElementById("hist-empty");
    tbody.innerHTML = `<tr><td colspan="6" class="hist-loading">${window.t("historymodal.loading")}</td></tr>`;
    empty.style.display = "none";

    try {
      const res = await fetch(`/api/history?date=${date}&limit=200`);
      if (!res.ok) throw new Error(res.status);
      const { entries } = await res.json();
      tbody.innerHTML = "";
      if (!entries.length) {
        empty.style.display = "block";
        return;
      }
      for (const e of entries) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="hist-time">${e.started_at || "—"}</td>
          <td class="hist-time">${e.ended_at || "—"}</td>
          <td class="hist-title" title="${_esc(e.path || "")}">${_esc(e.title || "—")}</td>
          <td class="hist-dur">${_fmtDuration(e.duration_played)}</td>
          <td><span class="hist-badge${e.end_reason === 'error' ? ' hist-badge--error' : ''}">${_esc(_reasonLabel(e))}</span></td>
          <td class="hist-pause">${e.had_pause ? window.t("historymodal.yes") : "—"}</td>
        `;
        tbody.appendChild(tr);
      }
    } catch (_) {
      tbody.innerHTML = `<tr><td colspan="6" class="hist-loading">${window.t("historymodal.load_error")}</td></tr>`;
    }
  }

  function _setDate(date) {
    _currentDate = date;
    document.getElementById("hist-date-label").textContent = _fmtDate(date);
    document.getElementById("hist-next-day").disabled = _shiftDate(date, 1) > _todayStr();
    _load(date);
  }

  // ── Aba: Estatísticas ──────────────────────────────────────────────────

  async function _loadStats() {
    const tbody  = document.getElementById("hist-stats-tbody");
    const empty  = document.getElementById("hist-stats-empty");
    const totals = document.getElementById("hist-stats-totals");
    tbody.innerHTML = `<tr><td colspan="4" class="hist-loading">${window.t("historymodal.loading")}</td></tr>`;
    empty.style.display = "none";
    totals.innerHTML = "";

    try {
      const res = await fetch("/api/history/stats");
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();

      totals.innerHTML = `
        <div class="hist-stat-card"><span class="hist-stat-val">${data.total_plays}</span><span class="hist-stat-lbl">${window.t("historymodal.total_plays")}</span></div>
        <div class="hist-stat-card"><span class="hist-stat-val">${data.total_hours}h</span><span class="hist-stat-lbl">${window.t("historymodal.total_hours")}</span></div>
        <div class="hist-stat-card"><span class="hist-stat-val">${data.total_days}</span><span class="hist-stat-lbl">${window.t("historymodal.total_days")}</span></div>
      `;

      tbody.innerHTML = "";
      if (!data.top_clips.length) {
        empty.style.display = "block";
        return;
      }
      data.top_clips.forEach((c, i) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="hist-rank">${i + 1}</td>
          <td class="hist-title" title="${_esc(c.path || "")}">${_esc(c.title || c.path || "—")}</td>
          <td class="hist-dur">${c.play_count}×</td>
          <td class="hist-dur">${_fmtDuration(c.total_seconds)}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (_) {
      tbody.innerHTML = `<tr><td colspan="4" class="hist-loading">${window.t("historymodal.stats_load_error")}</td></tr>`;
    }
  }

  // ── Abas ───────────────────────────────────────────────────────────────

  function _switchTab(tab) {
    document.querySelectorAll(".hist-tab").forEach(b => b.classList.toggle("hist-tab-active", b.dataset.tab === tab));
    document.getElementById("hist-panel-log").style.display   = tab === "log"   ? "" : "none";
    document.getElementById("hist-panel-stats").style.display = tab === "stats" ? "" : "none";
    if (tab === "stats") _loadStats();
  }

  // ── API pública ────────────────────────────────────────────────────────

  function openHistoryModal() {
    document.getElementById("history-modal").style.display = "flex";
    _switchTab("log");
    _setDate(_todayStr());
  }

  function _close() {
    document.getElementById("history-modal").style.display = "none";
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("hist-close").addEventListener("click", _close);
    document.getElementById("history-modal").addEventListener("click", e => {
      if (e.target === e.currentTarget) _close();
    });
    document.getElementById("hist-prev-day").addEventListener("click", () => {
      _setDate(_shiftDate(_currentDate, -1));
    });
    document.getElementById("hist-next-day").addEventListener("click", () => {
      const next = _shiftDate(_currentDate, 1);
      if (next <= _todayStr()) _setDate(next);
    });
    document.querySelectorAll(".hist-tab").forEach(btn => {
      btn.addEventListener("click", () => _switchTab(btn.dataset.tab));
    });
  });

  window.openHistoryModal = openHistoryModal;
})();
