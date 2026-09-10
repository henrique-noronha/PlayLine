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

  function open() {
    libBrowse.style.display = _hasNativePicker() ? "" : "none";
    form.reset();
    _setStatus(credStatus, "", "");
    modal.style.display = "flex";
    _load();
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
