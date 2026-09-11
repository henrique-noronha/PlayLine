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
  const ctCount    = document.getElementById("st-cities-count");
  const ctSearch   = document.getElementById("st-city-search");
  const ctResults  = document.getElementById("st-city-results");
  const ctStatus   = document.getElementById("st-cities-status");
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
    _setStatus(libStatus, "Carregando…", "loading");
    try {
      const r = await fetch("/api/settings", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      libPath.value = d.library_dir || "";
      curUserEl.placeholder = d.username || "";
      if (d.transition && typeof d.transition.duration === "number") trDur.value = d.transition.duration;
      if (d.library_missing) {
        _setStatus(libStatus,
          `A pasta configurada (${d.library_configured}) não foi encontrada. ` +
          `Usando a padrão até você escolher outra.`, "warn");
      } else {
        _setStatus(libStatus, "", "");
      }
    } catch (err) {
      _setStatus(libStatus, "Não foi possível carregar as configurações: " + err.message, "error");
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
  }

  function close() {
    modal.style.display = "none";
  }

  // ── Biblioteca ───────────────────────────────────────────────────────────

  async function _saveLibrary(body) {
    libSave.disabled = true;
    libReset.disabled = true;
    _setStatus(libStatus, "Verificando a pasta…", "loading");
    try {
      const r = await fetch("/api/settings/library", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        _setStatus(libStatus, d.detail || "Não foi possível alterar a pasta", "error");
        return;
      }
      libPath.value = d.library_dir || libPath.value;
      // O log de eventos recebe o aviso pelo evento WS "library_changed" (app.js).
      _setStatus(libStatus,
        d.changed ? "Biblioteca alterada para " + d.library_dir : "Essa já é a pasta atual",
        "success");
    } catch (err) {
      _setStatus(libStatus, "Erro de comunicação com o servidor: " + err.message, "error");
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
      _setStatus(libStatus, "Não foi possível abrir o seletor de pasta: " + err, "error");
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
      del.title = "Remover da lista";
      del.addEventListener("click", () => {
        _cities.splice(i, 1);
        _renderCities();
        _setStatus(ctStatus, "Lista alterada. Clique em Salvar cidades para aplicar.", "warn");
      });
      chip.appendChild(del);
      ctList.appendChild(chip);
    });
    ctCount.textContent = `${_cities.length}/${_citiesMax}`;
    // revalida os botões dos resultados da busca (limite ou já adicionada)
    ctResults.querySelectorAll("button[data-key]").forEach(b => {
      const dup = _cities.some(c => _key(c) === b.dataset.key);
      b.disabled = dup || _cities.length >= _citiesMax;
      b.textContent = dup ? "Já está na lista" : "Adicionar";
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
      _setStatus(ctStatus, "Não foi possível carregar as cidades: " + err.message, "error");
    }
  }

  async function _searchCities() {
    const q = ctSearch.value.trim();
    if (q.length < 2) { _setStatus(ctStatus, "Digite ao menos duas letras para buscar", "error"); return; }
    _setStatus(ctStatus, "Buscando…", "loading");
    ctResults.innerHTML = "";
    try {
      const r = await fetch("/api/cities/search?q=" + encodeURIComponent(q));
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _setStatus(ctStatus, d.detail || "Falha na busca", "error"); return; }
      const res = d.results || [];
      if (!res.length) { _setStatus(ctStatus, `Nenhuma cidade encontrada para "${q}"`, "warn"); return; }
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
          _setStatus(ctStatus, "Cidade adicionada. Clique em Salvar cidades para aplicar.", "warn");
        });
        row.appendChild(add);
        ctResults.appendChild(row);
      });
      _renderCities();   // define o rótulo/estado inicial dos botões
    } catch (err) {
      _setStatus(ctStatus, "Erro na busca: " + err.message, "error");
    }
  }

  async function _saveCities() {
    if (!_cities.length) { _setStatus(ctStatus, "Mantenha pelo menos uma cidade na lista", "error"); return; }
    ctSave.disabled = true;
    _setStatus(ctStatus, "Salvando…", "loading");
    try {
      const r = await fetch("/api/cities", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cities: _cities }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _setStatus(ctStatus, d.detail || "Não foi possível salvar", "error"); return; }
      _cities = d.cities || _cities;
      _renderCities();
      ctResults.innerHTML = "";
      ctSearch.value = "";
      _setStatus(ctStatus, `${_cities.length} cidade(s) salva(s)`, "success");
    } catch (err) {
      _setStatus(ctStatus, "Erro de comunicação com o servidor: " + err.message, "error");
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
    _setStatus(ctStatus, "Restaurando…", "loading");
    try {
      const r = await fetch("/api/cities", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset: true }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _setStatus(ctStatus, d.detail || "Não foi possível restaurar", "error"); return; }
      _cities = d.cities || [];
      ctResults.innerHTML = "";
      _renderCities();
      _setStatus(ctStatus, `Lista padrão restaurada (${_cities.length} cidades)`, "success");
    } catch (err) {
      _setStatus(ctStatus, "Erro de comunicação com o servidor: " + err.message, "error");
    }
  });

  // ── Transições (duração do fade) ─────────────────────────────────────────

  trSave.addEventListener("click", async () => {
    const dur = parseFloat(trDur.value);
    if (!(dur >= 0.2 && dur <= 3)) { _setStatus(trStatus, "Informe uma duração entre 0,2 e 3 segundos", "error"); return; }
    trSave.disabled = true;
    _setStatus(trStatus, "Salvando…", "loading");
    try {
      const r = await fetch("/api/settings/transition", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration: dur }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _setStatus(trStatus, d.detail || "Não foi possível salvar", "error"); return; }
      trDur.value = d.transition.duration;
      _setStatus(trStatus, `FTB de ${d.transition.duration}s salvo`, "success");
    } catch (err) {
      _setStatus(trStatus, "Erro de comunicação com o servidor: " + err.message, "error");
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

    if (!curUser || !curPass) { _setStatus(credStatus, "Informe o usuário e a senha atuais", "error"); return; }
    if (!newUser)             { _setStatus(credStatus, "Informe o novo usuário", "error"); return; }
    if (newPass.length < 4)   { _setStatus(credStatus, "A nova senha deve ter pelo menos 4 caracteres", "error"); return; }
    if (newPass !== newPass2) { _setStatus(credStatus, "A confirmação não confere com a nova senha", "error"); return; }

    credSave.disabled = true;
    _setStatus(credStatus, "Salvando…", "loading");
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
        _setStatus(credStatus, d.error || d.detail || "Não foi possível alterar as credenciais", "error");
        document.getElementById("st-cur-pass").value = "";
        return;
      }
      form.reset();
      curUserEl.placeholder = d.username || newUser;
      _setStatus(credStatus, "Credenciais atualizadas. Use o novo usuário e senha no próximo login.", "success");
      log("Usuário e senha de acesso alterados", "info");
    } catch (err) {
      _setStatus(credStatus, "Erro de comunicação com o servidor: " + err.message, "error");
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
