/* PlayLine — Motor de tradução da interface
   O idioma escolhido neste navegador fica em localStorage (mesmo padrão já
   usado para zoom, miniaturas e preferências de overlay). Sem escolha própria,
   vale o idioma padrão do servidor, definido no assistente de configuração
   inicial (/setup) e injetado na página como window.PLAYLINE_SERVER_LANG.

   Uso: elementos marcados com data-i18n="chave.aninhada" recebem o texto
   traduzido via textContent; data-i18n-placeholder e data-i18n-title fazem
   o mesmo para os atributos placeholder/title. Chamadas de JS usam
   window.t("chave.aninhada") diretamente. */
(function () {
  const LANG_KEY = "playline_lang";
  const SUPPORTED = ["pt", "en", "es"];
  const FALLBACK = "en";

  const DICTS = {
    pt: window.PLAYLINE_I18N_PT,
    en: window.PLAYLINE_I18N_EN,
    es: window.PLAYLINE_I18N_ES,
  };

  function getSavedLang() {
    try {
      const v = localStorage.getItem(LANG_KEY);
      return SUPPORTED.includes(v) ? v : null;
    } catch (_) {
      return null;
    }
  }

  function saveLang(lang) {
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch (_) {
      /* localStorage indisponível (perfil bloqueado), segue só na sessão atual */
    }
  }

  function getServerLang() {
    const v = window.PLAYLINE_SERVER_LANG;
    return SUPPORTED.includes(v) ? v : null;
  }

  let currentLang = getSavedLang() || getServerLang() || FALLBACK;

  function lookup(dict, path) {
    if (!dict) return undefined;
    let node = dict;
    for (const part of path.split(".")) {
      if (node == null) return undefined;
      node = node[part];
    }
    return typeof node === "string" ? node : undefined;
  }

  function lookupArr(dict, path) {
    if (!dict) return undefined;
    let node = dict;
    for (const part of path.split(".")) {
      if (node == null) return undefined;
      node = node[part];
    }
    return Array.isArray(node) ? node : undefined;
  }

  // tArr("secao.chave") -> lista traduzida (ex.: nomes dos dias da semana),
  // mesmo fallback en -> pt -> lista vazia (nunca undefined, nunca quebra
  // quem indexar o resultado por posição).
  function tArr(key) {
    return lookupArr(DICTS[currentLang], key) ?? lookupArr(DICTS[FALLBACK], key) ?? lookupArr(DICTS.pt, key) ?? [];
  }

  // Mensagem de erro de uma resposta da API. O servidor manda "code" + "params"
  // além do texto em português ("detail"/"error"); com um código conhecido a
  // frase sai no idioma do operador, senão mostra o texto do servidor como antes.
  function apiError(body, fallbackKey) {
    const d = body || {};
    if (d.code) {
      const key = "apierr." + d.code;
      const locale = currentLang === "pt" ? "pt-BR" : currentLang;
      const params = {};
      for (const k in (d.params || {})) {
        const v = d.params[k];
        params[k] = typeof v === "number" ? v.toLocaleString(locale) : v;
      }
      const s = t(key, params);
      if (s !== key) return s;
    }
    const raw = typeof d.detail === "string" ? d.detail : d.error;
    return raw || (fallbackKey ? t(fallbackKey) : "");
  }

  // t("secao.chave") -> string traduzida, com fallback en -> pt -> a própria
  // chave (nunca quebra a tela, mesmo se uma chave nova ainda não existir
  // em algum dicionário). t("secao.chave", {nome: "X"}) substitui "{{nome}}"
  // no texto resolvido, para mensagens como "«{{title}}» adicionado".
  function t(key, vars) {
    let s = (
      lookup(DICTS[currentLang], key) ??
      lookup(DICTS[FALLBACK], key) ??
      lookup(DICTS.pt, key) ??
      key
    );
    if (vars) {
      for (const k in vars) s = s.replace(new RegExp("\\{\\{" + k + "\\}\\}", "g"), vars[k]);
    }
    return s;
  }

  function applyTo(root) {
    root.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
    });
    root.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });
  }

  function applyAll() {
    document.documentElement.lang =
      { pt: "pt-BR", en: "en", es: "es" }[currentLang] || "en";
    applyTo(document);
    document.dispatchEvent(new CustomEvent("playline:lang-applied", { detail: { lang: currentLang } }));
  }

  function setLang(lang) {
    if (!SUPPORTED.includes(lang)) return;
    currentLang = lang;
    saveLang(lang);
    applyAll();
  }

  function initI18n() {
    applyAll(); // aplica o idioma deste navegador (ou o do servidor) imediatamente
  }

  window.t = t;
  window.tArr = tArr;
  window.apiError = apiError;
  window.PlaylineI18n = { t, tArr, apiError, setLang, getLang: () => currentLang, applyTo, SUPPORTED };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initI18n);
  } else {
    initI18n();
  }
})();
