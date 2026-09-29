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
        log(window.t('savesched.save_error_prefix') + (window.apiError(err) || `HTTP ${res.status}`), 'error');
      } else {
        log(window.t('savesched.saved', { title }), 'info');
        _closeSaveModal();
      }
    } catch (e) {
      log(window.t('savesched.save_error_prefix') + e.message, 'error');
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

  // Pluralização de "X clipe(s)": PT/EN/ES conjugam diferente (substantivo e,
  // em alguns casos, verbo/particípio), então a chave certa é escolhida aqui
  // pela contagem, nunca composta com "s" fixo como antes.
  function _clipCount(n) {
    return window.t(n === 1 ? 'savedscheds.clip_count_one' : 'savedscheds.clip_count_many', { n });
  }

  async function _renderList() {
    listWrap.innerHTML = `<p class="sv-scheds-empty">${window.t('savedscheds.loading')}</p>`;
    try {
      const res = await fetch('/api/saved-schedules');
      const data = await res.json();
      const schedules = data.schedules || [];
      if (!schedules.length) {
        listWrap.innerHTML = `<p class="sv-scheds-empty">${window.t('savedscheds.empty')}</p>`;
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
            <span class="sv-sched-card-meta">${_clipCount(s.item_count)} · ${date}</span>
          </div>
          <div class="sv-sched-card-btns">
            <button class="sv-sched-card-btn sv-sched-insert" data-id="${s.id}" data-title="${_esc(s.title)}" title="${_esc(window.t('savedscheds.insert_title'))}">${_esc(window.t('savedscheds.insert'))}</button>
            <button class="sv-sched-card-btn sv-sched-del" data-id="${s.id}" data-title="${_esc(s.title)}" title="${_esc(window.t('savedscheds.delete'))}">✕</button>
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
      listWrap.innerHTML = `<p class="sv-scheds-empty">${window.t('savedscheds.load_error')}</p>`;
    }
  }

  async function _insertSchedule(id, title) {
    try {
      const res = await fetch(`/api/saved-schedules/${id}/items`);
      if (!res.ok) { log(window.t('savedscheds.not_found'), 'error'); return; }
      const data = await res.json();
      const items = data.items;

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
        const n = newItems.length;
        log(window.t(n === 1 ? 'savedscheds.inserted_log_one' : 'savedscheds.inserted_log_many', { n }), 'info');
        showToast(
          title
            ? window.t('savedscheds.added_titled', { title })
            : window.t(n === 1 ? 'savedscheds.added_count_one' : 'savedscheds.added_count_many', { n }),
          "info"
        );
        if (typeof loadLibraryFiles === "function") loadLibraryFiles(_libCurrentFolder || "");
      };

      const missing = missingPaths.length;
      const total = items.length;
      const msg = missing > 0
        ? window.t(missing === 1 ? 'savedscheds.missing_warning_one' : 'savedscheds.missing_warning_many', { n: missing })
        : window.t('savedscheds.confirm_insert', { count: _clipCount(total) });
      _closeListModal();
      showConfirm(msg, doInsert);
    } catch (e) {
      log(window.t('savedscheds.insert_error_prefix') + e.message, 'error');
    }
  }

  function _deleteSchedule(id, title) {
    showConfirm(window.t('savedscheds.delete_confirm', { title: title || window.t('savedscheds.default_name') }), async () => {
      try {
        const res = await fetch(`/api/saved-schedules/${id}`, { method: 'DELETE' });
        if (!res.ok) { log(window.t('savedscheds.delete_error'), 'error'); return; }
        openSavedSchedsModal();
      } catch (e) {
        log(window.t('savedscheds.delete_error_prefix') + e.message, 'error');
      }
    });
  }

  function _esc(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
})();
