/* PlayLine — Modal de Configurações: pasta da biblioteca, usuário e senha */

(function () {
  const modal      = document.getElementById("settings-modal");
  const libPath    = document.getElementById("st-lib-path");
  const libBrowse  = document.getElementById("st-lib-browse");
  const libSave    = document.getElementById("st-lib-save");
  const libReset   = document.getElementById("st-lib-reset");
  const libStatus  = document.getElementById("st-lib-status");
  const form       = document.getElementById("st-cred-form");
  const credStatus = document.getElementById("st-cred-status");
  const credSave   = document.getElementById("st-cred-save");
  const curUserEl  = document.getElementById("st-cur-user");
  const trDur      = document.getElementById("st-fade-dur");
  const trSave     = document.getElementById("st-tr-save");
  const trStatus   = document.getElementById("st-tr-status");
  const ctList     = document.getElementById("st-cities-list");
  if (ctList) ctList.dataset.empty = window.t("settingsmsg.cities_empty");
  const ctCount    = document.getElementById("st-cities-count");
  const ctSearch   = document.getElementById("st-city-search");
  const ctResults  = document.getElementById("st-city-results");
  const ctStatus   = document.getElementById("st-cities-status");
  const langList   = document.getElementById("st-lang-list");
  const ctSave     = document.getElementById("st-cities-save");

  // O diálogo nativo só existe na janela do próprio servidor (main.py expõe
  // pick_folder). O PlayLine-Client também tem window.pywebview.api, mas sem
  // esse método, e uma pasta escolhida lá seria da máquina errada.
  function _hasNativePicker() {
    return !!(window.pywebview && window.pywebview.api &&
              typeof window.pywebview.api.pick_folder === "function");
  }

  function _setStatus(el, msg, kind) {
    el.textContent = msg || "";
    el.className = "st-status" + (kind ? " st-status-" + kind : "");
  }

  async function _load() {
    _setStatus(libStatus, window.t("settingsmsg.loading"), "loading");
    try {
      const r = await fetch("/api/settings", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      libPath.value = d.library_dir || "";
      curUserEl.placeholder = d.username || "";
      if (d.transition && typeof d.transition.duration === "number") trDur.value = d.transition.duration;
      if (d.library_missing) {
        _setStatus(libStatus,
          window.t("settingsmsg.lib_missing", { dir: d.library_configured }), "warn");
      } else {
        _setStatus(libStatus, "", "");
      }
    } catch (err) {
      _setStatus(libStatus, window.t("settingsmsg.load_failed") + err.message, "error");
    }
  }

  // ── Abas ─────────────────────────────────────────────────────────────────

  function _switchTab(name) {
    modal.querySelectorAll(".st-tab").forEach(b =>
      b.classList.toggle("st-tab-active", b.dataset.tab === name));
    modal.querySelectorAll(".st-panel").forEach(p =>
      p.classList.toggle("st-panel-active", p.dataset.panel === name));
  }

  modal.querySelectorAll(".st-tab").forEach(btn =>
    btn.addEventListener("click", () => _switchTab(btn.dataset.tab)));

  function open() {
    _switchTab("biblioteca");
    libBrowse.style.display = _hasNativePicker() ? "" : "none";
    form.reset();
    _setStatus(credStatus, "", "");
    ctResults.innerHTML = "";
    ctSearch.value = "";
    _setStatus(ctStatus, "", "");
    modal.style.display = "flex";
    _load();
    _loadCities();
    _renderLangTab();
  }

  function close() {
    modal.style.display = "none";
  }

  // ── Idioma ───────────────────────────────────────────────────────────────
  // O idioma fica neste navegador (localStorage, ver components/i18n.js) e
  // também vira o padrão do servidor, que vale para navegadores sem escolha
  // própria. Trocar recarrega a página: é o jeito simples e confiável de
  // garantir que todo texto já escrito em tela (inclusive mensagens de status
  // que não passam por data-i18n) reflita o novo idioma.
  function _renderLangTab() {
    if (!langList || !window.PlaylineI18n) return;
    const current = window.PlaylineI18n.getLang();
    const dicts = { pt: window.PLAYLINE_I18N_PT, en: window.PLAYLINE_I18N_EN, es: window.PLAYLINE_I18N_ES };
    langList.innerHTML = "";
    window.PlaylineI18n.SUPPORTED.forEach(code => {
      const d = dicts[code];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "st-lang-opt" + (code === current ? " st-lang-opt-active" : "");
      btn.innerHTML = `<span>${d.meta.name}</span><span class="st-lang-opt-hint">${d.meta.flag_hint}</span>`;
      btn.addEventListener("click", async () => {
        if (code === window.PlaylineI18n.getLang()) return;
        window.PlaylineI18n.setLang(code);
        try {
          await fetch("/api/settings/language", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ language: code }),
          });
        } catch (_) { /* sem servidor: vale só neste navegador */ }
        location.reload();
      });
      langList.appendChild(btn);
    });
  }

  // ── Biblioteca ───────────────────────────────────────────────────────────

  async function _saveLibrary(body) {
    libSave.disabled = true;
    libReset.disabled = true;
    _setStatus(libStatus, window.t("settingsmsg.checking_folder"), "loading");
    try {
      const r = await fetch("/api/settings/library", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        _setStatus(libStatus, window.apiError(d, "settingsmsg.folder_change_failed"), "error");
        return;
      }
      libPath.value = d.library_dir || libPath.value;
      // O log de eventos recebe o aviso pelo evento WS "library_changed" (app.js).
      _setStatus(libStatus,
        d.changed ? window.t("settingsmsg.lib_changed", { dir: d.library_dir }) : window.t("settingsmsg.lib_same"),
        "success");
    } catch (err) {
      _setStatus(libStatus, window.t("settingsmsg.server_error") + err.message, "error");
    } finally {
      libSave.disabled = false;
      libReset.disabled = false;
    }
  }

  libSave.addEventListener("click", () => _saveLibrary({ path: libPath.value }));
  libReset.addEventListener("click", () => _saveLibrary({ reset: true }));
  libPath.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); libSave.click(); }
  });

  libBrowse.addEventListener("click", async () => {
    try {
      const picked = await window.pywebview.api.pick_folder(libPath.value || "");
      if (picked) libPath.value = picked;
    } catch (err) {
      _setStatus(libStatus, window.t("settingsmsg.picker_failed") + err, "error");
    }
  });

  // ── Cidades do overlay de hora/temperatura ───────────────────────────────
  // Lista local; só vai para o servidor ao clicar em Salvar cidades.

  let _cities = [];
  let _citiesMax = 30;

  const _key = c => `${c.name},${c.state || ""}`.toLowerCase();

  function _renderCities() {
    ctList.innerHTML = "";
    _cities.forEach((c, i) => {
      const chip = document.createElement("span");
      chip.className = "st-city-chip";
      chip.innerHTML = `${esc(c.name)}<span class="uf">${esc(c.state || "")}</span>`;
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "✕";
      del.title = window.t("settingsmsg.city_remove_title");
      del.addEventListener("click", () => {
        _cities.splice(i, 1);
        _renderCities();
        _setStatus(ctStatus, window.t("settingsmsg.cities_changed_pending"), "warn");
      });
      chip.appendChild(del);
      ctList.appendChild(chip);
    });
    ctCount.textContent = `${_cities.length}/${_citiesMax}`;
    // revalida os botões dos resultados da busca (limite ou já adicionada)
    ctResults.querySelectorAll("button[data-key]").forEach(b => {
      const dup = _cities.some(c => _key(c) === b.dataset.key);
      b.disabled = dup || _cities.length >= _citiesMax;
      b.textContent = window.t(dup ? "settingsmsg.city_already" : "settingsmsg.city_add");
    });
  }

  async function _loadCities() {
    try {
      const r = await fetch("/api/cities", { cache: "no-store" });
      const d = await r.json();
      _cities = d.cities || [];
      if (typeof d.max === "number") _citiesMax = d.max;
      _renderCities();
    } catch (err) {
      _setStatus(ctStatus, window.t("settingsmsg.cities_load_failed") + err.message, "error");
    }
  }

  async function _searchCities() {
    const q = ctSearch.value.trim();
    if (q.length < 2) { _setStatus(ctStatus, window.t("settingsmsg.search_min"), "error"); return; }
    _setStatus(ctStatus, window.t("settingsmsg.searching"), "loading");
    ctResults.innerHTML = "";
    try {
      const r = await fetch("/api/cities/search?q=" + encodeURIComponent(q));
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _setStatus(ctStatus, window.apiError(d, "settingsmsg.search_failed"), "error"); return; }
      const res = d.results || [];
      if (!res.length) { _setStatus(ctStatus, window.t("settingsmsg.no_city_found", { q }), "warn"); return; }
      _setStatus(ctStatus, "", "");
      res.forEach(c => {
        const row = document.createElement("div");
        row.className = "st-city-result";
        row.innerHTML = `<span>${esc(c.name)} <small>${esc(c.state_name || c.state || "")}</small></span>`;
        const add = document.createElement("button");
        add.type = "button";
        add.dataset.key = _key(c);
        add.addEventListener("click", () => {
          if (_cities.length >= _citiesMax) return;
          _cities.push({ name: c.name, state: c.state, lat: c.lat, lon: c.lon });
          _renderCities();
          _setStatus(ctStatus, window.t("settingsmsg.city_added_pending"), "warn");
        });
        row.appendChild(add);
        ctResults.appendChild(row);
      });
      _renderCities();   // define o rótulo/estado inicial dos botões
    } catch (err) {
      _setStatus(ctStatus, window.t("settingsmsg.search_error") + err.message, "error");
    }
  }

  async function _saveCities() {
    if (!_cities.length) { _setStatus(ctStatus, window.t("settingsmsg.cities_min_one"), "error"); return; }
    ctSave.disabled = true;
    _setStatus(ctStatus, window.t("settingsmsg.saving"), "loading");
    try {
      const r = await fetch("/api/cities", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cities: _cities }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _setStatus(ctStatus, window.apiError(d, "settingsmsg.save_failed"), "error"); return; }
      _cities = d.cities || _cities;
      _renderCities();
      ctResults.innerHTML = "";
      ctSearch.value = "";
      _setStatus(ctStatus, window.t("settingsmsg.cities_saved", { n: _cities.length }), "success");
    } catch (err) {
      _setStatus(ctStatus, window.t("settingsmsg.server_error") + err.message, "error");
    } finally {
      ctSave.disabled = false;
    }
  }

  ctSave.addEventListener("click", _saveCities);
  document.getElementById("st-city-search-btn").addEventListener("click", _searchCities);
  ctSearch.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); _searchCities(); }
  });
  document.getElementById("st-cities-reset").addEventListener("click", async () => {
    _setStatus(ctStatus, window.t("settingsmsg.restoring"), "loading");
    try {
      const r = await fetch("/api/cities", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset: true }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _setStatus(ctStatus, window.apiError(d, "settingsmsg.restore_failed"), "error"); return; }
      _cities = d.cities || [];
      ctResults.innerHTML = "";
      _renderCities();
      _setStatus(ctStatus, window.t("settingsmsg.cities_restored", { n: _cities.length }), "success");
    } catch (err) {
      _setStatus(ctStatus, window.t("settingsmsg.server_error") + err.message, "error");
    }
  });

  // ── Transições (duração do fade) ─────────────────────────────────────────

  trSave.addEventListener("click", async () => {
    const dur = parseFloat(trDur.value);
    if (!(dur >= 0.2 && dur <= 3)) { _setStatus(trStatus, window.t("settingsmsg.tr_range"), "error"); return; }
    trSave.disabled = true;
    _setStatus(trStatus, window.t("settingsmsg.saving"), "loading");
    try {
      const r = await fetch("/api/settings/transition", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration: dur }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _setStatus(trStatus, window.apiError(d, "settingsmsg.save_failed"), "error"); return; }
      trDur.value = d.transition.duration;
      _setStatus(trStatus, window.t("settingsmsg.tr_saved", { s: d.transition.duration }), "success");
    } catch (err) {
      _setStatus(trStatus, window.t("settingsmsg.server_error") + err.message, "error");
    } finally {
      trSave.disabled = false;
    }
  });

  // ── Usuário e senha ──────────────────────────────────────────────────────

  form.addEventListener("submit", async e => {
    e.preventDefault();
    const curUser  = curUserEl.value.trim();
    const curPass  = document.getElementById("st-cur-pass").value;
    const newUser  = document.getElementById("st-new-user").value.trim();
    const newPass  = document.getElementById("st-new-pass").value;
    const newPass2 = document.getElementById("st-new-pass2").value;

    if (!curUser || !curPass) { _setStatus(credStatus, window.t("settingsmsg.cred_need_current"), "error"); return; }
    if (!newUser)             { _setStatus(credStatus, window.t("settingsmsg.cred_need_user"), "error"); return; }
    if (newPass.length < 4)   { _setStatus(credStatus, window.t("settingsmsg.cred_min_len"), "error"); return; }
    if (newPass !== newPass2) { _setStatus(credStatus, window.t("settingsmsg.cred_mismatch"), "error"); return; }

    credSave.disabled = true;
    _setStatus(credStatus, window.t("settingsmsg.saving"), "loading");
    try {
      const r = await fetch("/api/settings/credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_username: curUser, current_password: curPass,
          new_username: newUser, new_password: newPass,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) {
        _setStatus(credStatus, window.apiError(d, "settingsmsg.cred_failed"), "error");
        document.getElementById("st-cur-pass").value = "";
        return;
      }
      form.reset();
      curUserEl.placeholder = d.username || newUser;
      _setStatus(credStatus, window.t("settingsmsg.cred_saved"), "success");
      log(window.t("logmsg.credentials_changed"), "info");
    } catch (err) {
      _setStatus(credStatus, window.t("settingsmsg.server_error") + err.message, "error");
    } finally {
      credSave.disabled = false;
    }
  });

  // ── Abrir / fechar ───────────────────────────────────────────────────────

  document.getElementById("st-close").addEventListener("click", close);
  modal.addEventListener("click", e => { if (e.target === e.currentTarget) close(); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && modal.style.display !== "none") close();
  });

  window.openSettingsModal = open;
})();
