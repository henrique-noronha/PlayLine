(function () {
  // ── Modal: salvar roteiro ──────────────────────────────────────────────

  const saveModal   = document.getElementById('save-sched-modal');
  const saveInput   = document.getElementById('save-sched-input');
  const saveOkBtn   = document.getElementById('save-sched-ok');
  const saveCancelBtn = document.getElementById('save-sched-cancel');

  window.openSaveSchedModal = function () {
    saveInput.value = '';
    saveModal.style.display = 'flex';
    setTimeout(() => saveInput.focus(), 50);
  };

  function _closeSaveModal() {
    saveModal.style.display = 'none';
  }

  saveCancelBtn.addEventListener('click', _closeSaveModal);
  saveModal.addEventListener('click', e => { if (e.target === saveModal) _closeSaveModal(); });

  saveInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') saveOkBtn.click();
    if (e.key === 'Escape') _closeSaveModal();
  });

  saveOkBtn.addEventListener('click', async () => {
    const title = saveInput.value.trim();
    if (!title) { saveInput.focus(); return; }
    saveOkBtn.disabled = true;
    try {
      const res = await fetch('/api/saved-schedules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, items: state.schedule }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        log('Erro ao salvar roteiro: ' + (err.detail || `HTTP ${res.status}`), 'error');
      } else {
        log(`Roteiro "${title}" salvo.`, 'info');
        _closeSaveModal();
      }
    } catch (e) {
      log('Erro ao salvar roteiro: ' + e.message, 'error');
    } finally {
      saveOkBtn.disabled = false;
    }
  });

  // ── Modal: roteiros salvos ─────────────────────────────────────────────

  const listModal  = document.getElementById('saved-scheds-modal');
  const listWrap   = document.getElementById('saved-scheds-list');
  const closeBtn   = document.getElementById('saved-scheds-close');

  window.openSavedSchedsModal = async function () {
    listModal.style.display = 'flex';
    await _renderList();
  };

  function _closeListModal() {
    listModal.style.display = 'none';
  }

  closeBtn.addEventListener('click', _closeListModal);
  listModal.addEventListener('click', e => { if (e.target === listModal) _closeListModal(); });

  async function _renderList() {
    listWrap.innerHTML = '<p class="sv-scheds-empty">Carregando…</p>';
    try {
      const res = await fetch('/api/saved-schedules');
      const data = await res.json();
      const schedules = data.schedules || [];
      if (!schedules.length) {
        listWrap.innerHTML = '<p class="sv-scheds-empty">Nenhum roteiro salvo ainda.</p>';
        return;
      }
      listWrap.innerHTML = '';
      schedules.forEach(s => {
        const date = s.created_at ? s.created_at.replace('T', ' ').slice(0, 16) : '';
        const card = document.createElement('div');
        card.className = 'sv-sched-card';
        card.innerHTML = `
          <div class="sv-sched-card-info">
            <span class="sv-sched-card-title">${_esc(s.title)}</span>
            <span class="sv-sched-card-meta">${s.item_count} clipe${s.item_count !== 1 ? 's' : ''} · ${date}</span>
          </div>
          <div class="sv-sched-card-btns">
            <button class="sv-sched-card-btn sv-sched-insert" data-id="${s.id}" data-title="${_esc(s.title)}" title="Inserir no roteiro atual">Inserir</button>
            <button class="sv-sched-card-btn sv-sched-del" data-id="${s.id}" data-title="${_esc(s.title)}" title="Excluir">✕</button>
          </div>
        `;
        listWrap.appendChild(card);
      });

      listWrap.querySelectorAll('.sv-sched-insert').forEach(btn => {
        btn.addEventListener('click', () => _insertSchedule(parseInt(btn.dataset.id), btn.dataset.title || ''));
      });
      listWrap.querySelectorAll('.sv-sched-del').forEach(btn => {
        btn.addEventListener('click', () => {
          _closeListModal();
          _deleteSchedule(parseInt(btn.dataset.id), btn.dataset.title || '');
        });
      });
    } catch (e) {
      listWrap.innerHTML = '<p class="sv-scheds-empty">Erro ao carregar roteiros.</p>';
    }
  }

  async function _insertSchedule(id, title) {
    try {
      const res = await fetch(`/api/saved-schedules/${id}/items`);
      if (!res.ok) { log('Roteiro não encontrado.', 'error'); return; }
      const data = await res.json();
      const items = data.items;

      // Detectar clipes ausentes da biblioteca
      const paths = items.map(it => it.path).filter(Boolean);
      let missingPaths = [];
      if (paths.length) {
        try {
          const vRes = await fetch('/api/validate-paths', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths }),
          });
          if (vRes.ok) missingPaths = (await vRes.json()).missing || [];
        } catch (_) { /* ignora erros de validação */ }
      }

      const doInsert = () => {
        if (missingPaths.length) {
          missingPaths.forEach(p => window._markPathInvalid?.(p));
        }
        const now = Date.now();
        const newItems = items.map((it, i) => ({ ...it, id: `item-${now + i}` }));
        state.schedule = [...state.schedule, ...newItems];
        renderSchedule();
        syncOrderToServer();
        log(`${newItems.length} clipe${newItems.length !== 1 ? 's' : ''} inserido${newItems.length !== 1 ? 's' : ''} no roteiro.`, 'info');
        showToast(title ? `"${title}" adicionado` : `${newItems.length} clipe${newItems.length !== 1 ? 's' : ''} adicionado${newItems.length !== 1 ? 's' : ''}`, "info");
        if (typeof loadLibraryFiles === "function") loadLibraryFiles(_libCurrentFolder || "");
      };

      const missing = missingPaths.length;
      const total = items.length;
      const msg = missing > 0
        ? `${missing} clipe${missing !== 1 ? 's' : ''} não ${missing !== 1 ? 'estão' : 'está'} mais na biblioteca e ${missing !== 1 ? 'aparecerão' : 'aparecerá'} com borda vermelha. Inserir mesmo assim?`
        : `Inserir ${total} clipe${total !== 1 ? 's' : ''} no roteiro atual?`;
      _closeListModal();
      showConfirm(msg, doInsert);
    } catch (e) {
      log('Erro ao inserir roteiro: ' + e.message, 'error');
    }
  }

  function _deleteSchedule(id, title) {
    showConfirm(`Excluir "${title || 'este roteiro'}"? Esta ação não pode ser desfeita.`, async () => {
      try {
        const res = await fetch(`/api/saved-schedules/${id}`, { method: 'DELETE' });
        if (!res.ok) { log('Erro ao excluir roteiro.', 'error'); return; }
        openSavedSchedsModal();
      } catch (e) {
        log('Erro ao excluir roteiro: ' + e.message, 'error');
      }
    });
  }

  function _esc(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
})();
