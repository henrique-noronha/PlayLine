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
    if (h > 0) return `${h}h ${String(m).padStart(2,"0")}m ${String(s).padStart(2,"0")}s`;
    if (m > 0) return `${m}m ${String(s).padStart(2,"0")}s`;
    return `${s}s`;
  }

  async function _load(date) {
    const tbody = document.getElementById("hist-tbody");
    const empty = document.getElementById("hist-empty");
    tbody.innerHTML = `<tr><td colspan="6" class="hist-loading">Carregando…</td></tr>`;
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
          <td><span class="hist-badge">${_esc(e.end_reason_label || e.end_reason || "—")}</span></td>
          <td class="hist-pause">${e.had_pause ? "Sim" : "—"}</td>
        `;
        tbody.appendChild(tr);
      }
    } catch (_) {
      tbody.innerHTML = `<tr><td colspan="6" class="hist-loading">Erro ao carregar histórico.</td></tr>`;
    }
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function _setDate(date) {
    _currentDate = date;
    document.getElementById("hist-date-label").textContent = _fmtDate(date);
    document.getElementById("hist-next-day").disabled = _shiftDate(date, 1) > _todayStr();
    _load(date);
  }

  function openHistoryModal() {
    document.getElementById("history-modal").style.display = "flex";
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
  });

  window.openHistoryModal = openHistoryModal;
})();
