/* PlayLine — Painéis de overlay, recorte e menu de engrenagem do roteiro */

// ── Popup de overlay por clipe ──────────────────────────────────────────────

let _cop    = null;
let _copIdx = null;

function _closeCop() {
  if (_cop) {
    _cop.querySelectorAll(".logo-picker-dropdown.open").forEach(d => d.classList.remove("open"));
    _cop.style.display = "none";
  }
  _copIdx = null;
}

function _copGetOrCreate() {
  if (_cop) return _cop;
  const el = document.createElement("div");
  el.id = "cop-popup";
  el.className = "cop-popup";
  el.style.display = "none";
  el.innerHTML = `
    <div class="cop-header">
      <label class="cop-enable-label">
        <input type="checkbox" id="cop-enable" />
        <span>${window.t("clipoverlay.enable_label")}</span>
      </label>
      <button id="cop-close" class="cop-close-btn">✕</button>
    </div>
    <div id="cop-body" class="cop-body">
      <div class="cop-row">
        <span class="cop-lbl">${window.t("logo.logo1")}</span>
        <button class="btn-logo-toggle cop-tog" id="cop-tog-1"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg></button>
        <div class="cop-pick-wrap">
          <button class="cop-pbtn" id="cop-pbtn-1">— ▾</button>
          <div class="logo-picker-dropdown" id="cop-pdd-1"></div>
        </div>
      </div>
      <div class="cop-row">
        <span class="cop-lbl">${window.t("logo.logo2")}</span>
        <button class="btn-logo-toggle cop-tog" id="cop-tog-2"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg></button>
        <div class="cop-pick-wrap">
          <button class="cop-pbtn" id="cop-pbtn-2">— ▾</button>
          <div class="logo-picker-dropdown" id="cop-pdd-2"></div>
        </div>
      </div>
      <div class="cop-row">
        <span class="cop-lbl">${window.t("logo.clock_temp")}</span>
        <button class="btn-logo-toggle cop-tog" id="cop-tog-text"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg></button>
        <div class="cop-text-opts">
          <div class="logo-picker-item" id="cop-chk-time">
            <span class="logo-picker-check" id="cop-chk-time-mark">✓</span>
            <span class="logo-picker-name">${window.t("logo.clock")}</span>
          </div>
          <div class="logo-picker-item" id="cop-chk-temp">
            <span class="logo-picker-check" id="cop-chk-temp-mark">✓</span>
            <span class="logo-picker-name">${window.t("logo.temp")}</span>
          </div>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(el);
  _cop = el;

  el.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", _closeCop);
  el.querySelector("#cop-close").addEventListener("click", _closeCop);

  el.querySelector("#cop-enable").addEventListener("change", function () {
    if (_copIdx === null) return;
    const item = state.schedule[_copIdx];
    if (!item) return;
    item.clip_overlays = this.checked ? _copDefaultConfig() : null;
    _copRefreshBody(item);
    _copMarkRow(_copIdx, !!item.clip_overlays);
    syncOrderToServer();
  });

  ["1", "2", "text"].forEach(slot => {
    el.querySelector(`#cop-tog-${slot}`).addEventListener("click", e => {
      e.stopPropagation();
      if (_copIdx === null) return;
      const item = state.schedule[_copIdx];
      if (!item?.clip_overlays) return;
      const key = slot === "text" ? "text" : `logo${slot}`;
      item.clip_overlays[key].active = !item.clip_overlays[key].active;
      _copRefreshBody(item);
      syncOrderToServer();
    });
  });

  [1, 2].forEach(slot => {
    const pbtn = el.querySelector(`#cop-pbtn-${slot}`);
    const pdd  = el.querySelector(`#cop-pdd-${slot}`);
    pbtn.addEventListener("click", e => {
      e.stopPropagation();
      const isOpen = pdd.classList.contains("open");
      el.querySelectorAll(".logo-picker-dropdown").forEach(d => d.classList.remove("open"));
      if (!isOpen) pdd.classList.add("open");
    });
    pdd.addEventListener("click", e => e.stopPropagation());
  });

  ["time", "temp"].forEach(key => {
    el.querySelector(`#cop-chk-${key}`).addEventListener("click", e => {
      e.stopPropagation();
      if (_copIdx === null) return;
      const item = state.schedule[_copIdx];
      if (!item?.clip_overlays?.text) return;
      item.clip_overlays.text[`show_${key}`] = !item.clip_overlays.text[`show_${key}`];
      _copRefreshBody(item);
      syncOrderToServer();
    });
  });

  return el;
}

function _copDefaultConfig() {
  const ls = (typeof _logoState !== "undefined") ? _logoState : {};
  const ts = (typeof _textState !== "undefined") ? _textState : {};
  return {
    logo1: { active: ls[1]?.active ?? false, filename: ls[1]?.filename ?? "", corner: ls[1]?.corner ?? "br" },
    logo2: { active: ls[2]?.active ?? false, filename: ls[2]?.filename ?? "", corner: ls[2]?.corner ?? "bl" },
    text:  { active: ts.active ?? false, show_time: ts.show_time ?? true, show_temp: ts.show_temp ?? true },
  };
}

function _copRefreshBody(item) {
  const el = _cop;
  if (!el) return;
  const co      = item.clip_overlays;
  const enabled = !!co;
  el.querySelector("#cop-enable").checked = enabled;
  const body = el.querySelector("#cop-body");
  body.style.opacity       = enabled ? "1" : "0.4";
  body.style.pointerEvents = enabled ? "" : "none";
  if (!enabled) return;

  [1, 2].forEach(slot => {
    const cfg = co[`logo${slot}`] || {};
    el.querySelector(`#cop-tog-${slot}`).classList.toggle("active", !!cfg.active);
    const fname = cfg.filename || "—";
    el.querySelector(`#cop-pbtn-${slot}`).textContent = fname + " ▾";

    const pdd   = el.querySelector(`#cop-pdd-${slot}`);
    const files = (typeof _logoFiles !== "undefined" ? _logoFiles : []);
    pdd.innerHTML = "";
    if (!files.length) {
      pdd.innerHTML = `<div class="logo-picker-empty">${esc(window.t("clipoverlay.empty_logos_folder"))}</div>`;
    } else {
      files.forEach(f => {
        const it  = document.createElement("div");
        it.className = "logo-picker-item";
        it.innerHTML = `<span class="logo-picker-check">${cfg.filename === f ? "✓" : ""}</span><span class="logo-picker-name">${esc(f)}</span>`;
        it.addEventListener("click", e => {
          e.stopPropagation();
          if (_copIdx === null) return;
          const itm = state.schedule[_copIdx];
          if (!itm?.clip_overlays) return;
          itm.clip_overlays[`logo${slot}`].filename = f;
          pdd.classList.remove("open");
          _copRefreshBody(itm);
          syncOrderToServer();
        });
        pdd.appendChild(it);
      });
    }
  });

  const text = co.text || {};
  el.querySelector("#cop-tog-text").classList.toggle("active", !!text.active);
  el.querySelector("#cop-chk-time-mark").style.visibility = text.show_time !== false ? "" : "hidden";
  el.querySelector("#cop-chk-temp-mark").style.visibility = text.show_temp !== false ? "" : "hidden";
}

function _copMarkRow(idx, hasConfig) {
  const row = document.querySelector(`.schedule-item[data-index="${idx}"]`);
  if (!row) return;
  row.classList.toggle("has-clip-overlays", hasConfig);
  const btn = row.querySelector(".btn-clip-overlay");
  if (btn) btn.classList.toggle("configured", hasConfig);
}

function openClipOverlayPanel(item, idx, anchorEl) {
  const el = _copGetOrCreate();
  _copIdx = idx;
  _copRefreshBody(item);

  el.style.display = "block";
  const W    = 260;
  const H    = el.offsetHeight;
  const rect = anchorEl.getBoundingClientRect();
  let left = rect.left - W - 6;
  let top  = rect.top;
  if (left < 4) left = rect.right + 6;
  if (top + H > window.innerHeight - 8) top = rect.bottom - H;
  if (top < 4) top = 4;
  el.style.left = left + "px";
  el.style.top  = top  + "px";
}

// ── Gear menu (dropdown do botão ⚙) ────────────────────────────────────────

function _gdSetTransitionLabel(item) {
  if (!_gd) return;
  const t = item?.transition;
  const has = t === "fade" || t === "cut";
  _gd.querySelector("#gd-transition-val").textContent = has ? _TRANSITION_ITEM_LABELS[t] : window.t("gear.transition_default");
  _gd.querySelector("#gd-transition").classList.toggle("active", has);
}

let _gd = null;
let _gdItem = null, _gdIdx = null, _gdAnchor = null;

function _closeGd() {
  if (_gd) _gd.style.display = "none";
  _gdItem = null; _gdIdx = null; _gdAnchor = null;
}

function _getOrCreateGd() {
  if (_gd) return _gd;
  const el = document.createElement("div");
  el.id = "gear-dropdown";
  el.className = "gear-dropdown";
  el.style.display = "none";
  el.innerHTML = `
    <div class="gear-item" id="gd-overlays">⊡ ${window.t("gear.overlays")}</div>
    <div class="gear-item" id="gd-transition" title="${esc(window.t("gear.transition_title"))}">◐ ${window.t("gear.transition")}<b id="gd-transition-val">${window.t("gear.transition_default")}</b></div>
    <div class="gear-sep"></div>
    <div class="gear-item" id="gd-trim">✂ ${window.t("gear.trim")}</div>
  `;
  document.body.appendChild(el);
  _gd = el;
  el.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", _closeGd);

  el.querySelector("#gd-overlays").addEventListener("click", () => {
    const item = _gdItem, idx = _gdIdx, anchor = _gdAnchor;
    _closeGd();
    if (idx !== null) openClipOverlayPanel(item, idx, anchor);
  });
  el.querySelector("#gd-transition").addEventListener("click", () => {
    const item = _gdItem, idx = _gdIdx;
    if (!item || idx === null) return;
    const order = [null, "fade", "cut"];
    const next = order[(order.indexOf(item.transition || null) + 1) % order.length];
    if (next) item.transition = next; else delete item.transition;
    _gdSetTransitionLabel(item);
    _markRowTransition(idx, item.transition || null);
    syncOrderToServer();
  });
  el.querySelector("#gd-trim").addEventListener("click", () => {
    if (el.querySelector("#gd-trim").classList.contains("disabled")) return;
    const item = _gdItem, idx = _gdIdx, anchor = _gdAnchor;
    _closeGd();
    if (idx !== null) openClipTrimPanel(item, idx, anchor);
  });
  return el;
}

function openGearMenu(item, idx, anchorEl) {
  const el = _getOrCreateGd();
  _gdItem = item; _gdIdx = idx; _gdAnchor = anchorEl;
  el.querySelector("#gd-overlays").classList.toggle("active", !!item.clip_overlays);
  _gdSetTransitionLabel(item);
  el.querySelector("#gd-trim").classList.toggle("active", hasTrim(item));
  el.querySelector("#gd-trim").classList.toggle("disabled", !!item.live);
  el.style.display = "block";
  const W = el.offsetWidth, H = el.offsetHeight;
  const rect = anchorEl.getBoundingClientRect();
  let left = rect.left - W - 6, top = rect.top;
  if (left < 4) left = rect.right + 6;
  if (top + H > window.innerHeight - 8) top = rect.bottom - H;
  if (top < 4) top = 4;
  el.style.left = left + "px";
  el.style.top  = top  + "px";
}

// ── Popup de recorte de clipe ───────────────────────────────────────────────

let _ct = null;
let _ctIdx = null;

function _closeCt() {
  if (_ct) _ct.style.display = "none";
  _ctIdx = null;
}

function _ctGetOrCreate() {
  if (_ct) return _ct;
  const el = document.createElement("div");
  el.id = "ct-popup";
  el.className = "ct-popup";
  el.style.display = "none";
  el.innerHTML = `
    <div class="ct-header">
      <span>✂ ${window.t("gear.trim")}</span>
      <button id="ct-close" class="ct-close-btn">✕</button>
    </div>
    <div class="ct-body">
      <div class="ct-row">
        <label class="ct-lbl">${window.t("trim.start_label")}</label>
        <input id="ct-start-inp" class="ct-inp" type="text" placeholder="0:00" autocomplete="off" spellcheck="false" />
      </div>
      <div class="ct-row">
        <label class="ct-lbl">${window.t("trim.end_label")}</label>
        <input id="ct-end-inp" class="ct-inp" type="text" placeholder="${esc(window.t("trim.end_placeholder"))}" autocomplete="off" spellcheck="false" />
      </div>
      <div class="ct-dur-row">
        <span class="ct-dur-lbl">${window.t("trim.effective_duration")}</span>
        <span id="ct-eff-dur" class="ct-eff-dur">—</span>
      </div>
      <div class="ct-footer-row">
        <button id="ct-clear-btn" class="ct-clear-btn">${window.t("trim.clear")}</button>
        <button id="ct-ok-btn" class="ct-ok-btn">OK</button>
      </div>
    </div>
  `;
  document.body.appendChild(el);
  _ct = el;
  el.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", _closeCt);
  el.querySelector("#ct-close").addEventListener("click", _closeCt);

  const startInp = el.querySelector("#ct-start-inp");
  const endInp   = el.querySelector("#ct-end-inp");
  const effDur   = el.querySelector("#ct-eff-dur");

  function calcEff() {
    if (_ctIdx === null) return null;
    const item = state.schedule[_ctIdx];
    if (!item || !item.duration) return null;
    const s  = parseTime(startInp.value);
    const e2 = parseTime(endInp.value);
    const st = s  != null && s  > 0 ? s  : 0;
    const en = e2 != null && e2 > 0 ? e2 : item.duration;
    return Math.max(0, en - st);
  }

  function refreshEffDur() {
    const eff = calcEff();
    effDur.textContent = eff != null ? fmt(eff) : "—";

    if (_ctIdx === null) return;
    const item = state.schedule[_ctIdx];
    if (!item || !item.duration) return;
    const dur = item.duration;
    const s  = parseTime(startInp.value);
    const e2 = parseTime(endInp.value);
    const sErr  = s  != null && (s  < 0 || s  >= dur);
    const eErr  = e2 != null && (e2 <= 0 || e2 >  dur);
    const st = s  != null && s  > 0 ? s  : 0;
    const en = e2 != null && e2 > 0 ? e2 : dur;
    const crossErr = !sErr && !eErr && st >= en;
    startInp.classList.toggle("ct-inp-error", sErr || crossErr);
    endInp.classList.toggle("ct-inp-error",   eErr || crossErr);
  }

  function commit() {
    if (_ctIdx === null) return;
    const item = state.schedule[_ctIdx];
    if (!item || !item.duration) return;
    const dur = item.duration;

    let s  = parseTime(startInp.value);
    let e2 = parseTime(endInp.value);

    if (s  != null) { s  = Math.max(0, Math.min(s,  dur)); startInp.value = s  > 0   ? fmtSec(s)  : ""; }
    if (e2 != null) { e2 = Math.max(0, Math.min(e2, dur)); endInp.value   = e2 < dur ? fmtSec(e2) : ""; }

    const st = s  != null && s  > 0 ? s  : 0;
    const en = e2 != null && e2 > 0 ? e2 : dur;
    if (st >= en) return;

    startInp.classList.remove("ct-inp-error");
    endInp.classList.remove("ct-inp-error");

    if (s  != null && s  > 0)   item.start_time = s;  else delete item.start_time;
    if (e2 != null && e2 < dur) item.end_time   = e2; else delete item.end_time;
    _ctMarkRow(_ctIdx);
    updateStartTimes();
    syncOrderToServer();
  }

  startInp.addEventListener("input", refreshEffDur);
  endInp.addEventListener("input",   refreshEffDur);

  function commitAndClose() { commit(); _closeCt(); }
  el.querySelector("#ct-ok-btn").addEventListener("click", commitAndClose);
  startInp.addEventListener("keydown", e => { if (e.key === "Enter") commitAndClose(); });
  endInp.addEventListener("keydown",   e => { if (e.key === "Enter") commitAndClose(); });

  el.querySelector("#ct-clear-btn").addEventListener("click", () => {
    if (_ctIdx === null) return;
    const item = state.schedule[_ctIdx];
    if (!item) return;
    delete item.start_time; delete item.end_time;
    startInp.value = ""; endInp.value = "";
    effDur.textContent = item.duration > 0 ? fmt(item.duration) : "—";
    _ctMarkRow(_ctIdx);
    updateStartTimes();
    syncOrderToServer();
  });

  return el;
}

function _ctMarkRow(idx) {
  const row  = document.querySelector(`.schedule-item[data-index="${idx}"]`);
  const item = idx !== null ? state.schedule[idx] : null;
  if (!row || !item) return;
  const trimOn = hasTrim(item);
  row.classList.toggle("has-trim", trimOn);
  const durEl = row.querySelector(`.item-dur[data-idx="${idx}"]`);
  if (durEl && item.duration > 0 && !item.live) {
    durEl.className = `item-dur${trimOn ? ' trim-active' : ''}`;
    durEl.textContent = trimOn ? ('✂ ' + fmt(effectiveDuration(item))) : fmt(item.duration);
  }
  if (_gd && _gdIdx === idx) {
    _gd.querySelector("#gd-trim").classList.toggle("active", trimOn);
  }
}

function openClipTrimPanel(item, idx, anchorEl) {
  const el = _ctGetOrCreate();
  _ctIdx = idx;
  const startInp = el.querySelector("#ct-start-inp");
  const endInp   = el.querySelector("#ct-end-inp");
  const effDur   = el.querySelector("#ct-eff-dur");
  startInp.value = item.start_time > 0 ? fmtSec(item.start_time) : "";
  endInp.value   = item.end_time   > 0 ? fmtSec(item.end_time)   : "";
  endInp.placeholder = item.duration > 0 ? fmtSec(item.duration) : window.t("trim.end_placeholder");
  const eff = effectiveDuration(item);
  effDur.textContent = item.duration > 0 ? fmt(eff) : "—";
  el.style.display = "block";
  const W = 224, H = el.offsetHeight;
  const rect = anchorEl.getBoundingClientRect();
  let left = rect.left - W - 6, top = rect.top;
  if (left < 4) left = rect.right + 6;
  if (top + H > window.innerHeight - 8) top = rect.bottom - H;
  if (top < 4) top = 4;
  el.style.left = left + "px";
  el.style.top  = top  + "px";
}
