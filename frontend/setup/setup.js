/* PlayLine — Assistente de configuração inicial
   Três etapas: idioma, usuário e senha (opcional manter os atuais) e pasta da
   biblioteca. Nada é gravado até "Concluir": POST /api/setup/complete valida
   tudo no servidor, grava, abre a sessão e o painel carrega já logado. Se o
   servidor recusar algo, a resposta diz a etapa ("step") e o assistente volta
   para ela com a mensagem traduzida (window.apiError). */
(function () {
  const STEPS = 3;
  const $ = (id) => document.getElementById(id);
  const t = (k, v) => window.t(k, v);

  let step = 0;
  let info = null;        // GET /api/setup/state
  let busy = false;

  const errEl = $("setup-error");
  const btnBack = $("btn-back");
  const btnNext = $("btn-next");

  function showError(msg) { errEl.textContent = msg || ""; }

  // ── Etapa 1: idioma ────────────────────────────────────────────────────
  function renderLangs() {
    const list = $("setup-lang-list");
    const current = window.PlaylineI18n.getLang();
    const dicts = { pt: window.PLAYLINE_I18N_PT, en: window.PLAYLINE_I18N_EN, es: window.PLAYLINE_I18N_ES };
    list.innerHTML = "";
    window.PlaylineI18n.SUPPORTED.forEach((code) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "setup-lang-opt" + (code === current ? " selected" : "");
      btn.innerHTML = `<span>${dicts[code].meta.name}</span><span class="setup-lang-hint">${dicts[code].meta.flag_hint}</span>`;
      btn.addEventListener("click", () => {
        window.PlaylineI18n.setLang(code);   // retraduz o assistente na hora
        showError("");
      });
      list.appendChild(btn);
    });
  }

  // ── Etapa 2: credenciais ───────────────────────────────────────────────
  const credMode = () => document.querySelector('input[name="cred-mode"]:checked').value;

  function syncCredMode() {
    $("cred-fields").classList.toggle("disabled", credMode() !== "new");
  }

  function validateCredentials() {
    if (credMode() !== "new") return null;
    const user = $("cred-user").value.trim();
    const pass = $("cred-pass").value;
    const min = (info && info.password_min) || 4;
    if (!user) return t("settingsmsg.cred_need_user");
    if (/\s/.test(user)) return t("apierr.cred_user_spaces");
    if (pass.length < min) return t("apierr.cred_pass_too_short", { min });
    if (pass !== $("cred-pass2").value) return t("settingsmsg.cred_mismatch");
    return null;
  }

  // ── Etapa 3: biblioteca ────────────────────────────────────────────────
  const libMode = () => document.querySelector('input[name="lib-mode"]:checked').value;

  function syncLibMode() {
    $("lib-custom-row").classList.toggle("disabled", libMode() !== "custom");
  }

  function validateLibrary() {
    if (libMode() === "custom" && !$("lib-path").value.trim()) return t("apierr.lib_path_required");
    return null;
  }

  // O seletor de pasta nativo só existe na janela do próprio PlayLine
  // (pywebview), e a API dele é injetada de forma assíncrona.
  function enableBrowse() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder) {
      $("lib-browse").hidden = false;
    }
  }
  window.addEventListener("pywebviewready", enableBrowse);

  $("lib-browse").addEventListener("click", async () => {
    try {
      const picked = await window.pywebview.api.pick_folder($("lib-path").value || (info && info.library_dir) || "");
      if (picked) {
        $("lib-path").value = picked;
        document.querySelector('input[name="lib-mode"][value="custom"]').checked = true;
        syncLibMode();
      }
    } catch (err) {
      showError(t("settingsmsg.picker_failed") + err);
    }
  });

  // ── Navegação ──────────────────────────────────────────────────────────
  function render() {
    document.querySelectorAll(".setup-panel").forEach((p) => {
      p.hidden = Number(p.dataset.panel) !== step;
    });
    document.querySelectorAll("#setup-steps li").forEach((li) => {
      const n = Number(li.dataset.step);
      li.classList.toggle("active", n === step);
      li.classList.toggle("done", n < step);
    });
    $("setup-progress").textContent = t("setup.step_of", { n: step + 1, total: STEPS });
    btnBack.style.visibility = step === 0 ? "hidden" : "visible";
    btnNext.textContent = busy ? t("setup.saving") : t(step === STEPS - 1 ? "setup.finish" : "setup.next");
    btnNext.disabled = busy;
    btnBack.disabled = busy;
    if (info) {
      $("cred-keep-label").textContent = t("setup.cred_opt_keep", { user: info.username });
    }
    renderLangs();
    const focusable = document.querySelector(`.setup-panel[data-panel="${step}"] input:not([type=radio]), .setup-panel[data-panel="${step}"] button`);
    if (focusable && document.activeElement === document.body) focusable.focus();
  }

  function goTo(n) {
    step = Math.max(0, Math.min(STEPS - 1, n));
    showError("");
    render();
  }

  async function finish() {
    const creds = credMode() === "new"
      ? { username: $("cred-user").value.trim(), password: $("cred-pass").value }
      : null;
    const mode = libMode();
    const body = {
      language: window.PlaylineI18n.getLang(),
      credentials: creds,
      library_path: mode === "custom" ? $("lib-path").value.trim() : null,
      library_reset: mode === "default" && !!(info && info.library_custom),
    };
    busy = true;
    render();
    try {
      const r = await fetch("/api/setup/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) {
        location.href = "/";
        return;
      }
      if (d.code === "setup_done") { location.href = "/"; return; }
      busy = false;
      const back = { language: 0, credentials: 1, library: 2 }[d.step];
      if (back !== undefined) goTo(back);
      else render();
      showError(window.apiError(d, "settingsmsg.save_failed"));
    } catch (err) {
      busy = false;
      render();
      showError(t("settingsmsg.server_error") + err.message);
    }
  }

  btnBack.addEventListener("click", () => goTo(step - 1));
  btnNext.addEventListener("click", () => {
    if (busy) return;
    const err = step === 1 ? validateCredentials() : step === 2 ? validateLibrary() : null;
    if (err) { showError(err); return; }
    if (step < STEPS - 1) goTo(step + 1);
    else finish();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.target.matches("button")) {
      e.preventDefault();
      btnNext.click();
    }
  });

  document.querySelectorAll('input[name="cred-mode"]').forEach((r) => r.addEventListener("change", () => { syncCredMode(); showError(""); }));
  document.querySelectorAll('input[name="lib-mode"]').forEach((r) => r.addEventListener("change", () => { syncLibMode(); showError(""); }));
  $("lib-path").addEventListener("input", () => {
    document.querySelector('input[name="lib-mode"][value="custom"]').checked = true;
    syncLibMode();
  });
  // Troca de idioma: textos de data-i18n já são refeitos pelo i18n.js; os
  // montados aqui (progresso, botões, rótulo com o usuário) são refeitos agora.
  document.addEventListener("playline:lang-applied", () => { if (info) render(); });

  // ── Estado inicial ─────────────────────────────────────────────────────
  async function init() {
    enableBrowse();
    let r, d;
    try {
      r = await fetch("/api/setup/state");
      d = await r.json().catch(() => ({}));
    } catch (err) {
      showError(t("settingsmsg.server_error") + err.message);
      return;
    }
    if (r.status === 409) { location.href = "/"; return; }
    if (!r.ok) {
      document.querySelectorAll(".setup-panel, .setup-steps, .setup-footer").forEach((el) => { el.hidden = true; });
      showError(window.apiError(d));
      return;
    }
    info = d;
    // Idioma: o deste navegador, senão o que já estiver salvo no servidor
    // (quem atualiza), senão o padrão do i18n.js (inglês).
    let saved = null;
    try { saved = localStorage.getItem("playline_lang"); } catch (_) {}
    if (!window.PlaylineI18n.SUPPORTED.includes(saved) && info.language) {
      window.PlaylineI18n.setLang(info.language);
    }
    // Credenciais: sugere o usuário atual; senha sempre em branco.
    $("cred-user").value = info.username || "";
    // Biblioteca: com pasta própria configurada, "manter" vem marcado; senão, a padrão.
    $("lib-current").textContent = info.library_dir;
    $("lib-default").textContent = info.library_default;
    $("lib-keep-row").hidden = !info.library_custom;
    document.querySelector(`input[name="lib-mode"][value="${info.library_custom ? "keep" : "default"}"]`).checked = true;
    syncCredMode();
    syncLibMode();
    render();
  }

  init();
})();
