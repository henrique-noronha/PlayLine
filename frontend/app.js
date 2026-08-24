/* PlayLine — app.js: estado global, eventos do servidor e bootstrap */

const state = {
  ws: null,
  connected: false,
  schedule: [],
  currentIndex: -1,
  playing: false,
  paused: false,
  currentItemStartTime: null,
  pausedAt: null,       // timestamp de quando pausou
  totalPausedMs: 0,     // soma de todos os tempos pausados no clipe atual
  mpvAlive: true,       // false após mpv_closed, true após mpv_ready / now_playing
  repeat: false,
};

let _remainingTimer = null;

// Carregamento diferido do preview: aguarda o primeiro evento "position" para
// saber onde abrir o vídeo via #t=N, evitando o seek manual que congela o browser.
let _pendingLoad         = null;   // { path, paused } enquanto aguarda posição
let _pendingLoadTimeout  = null;   // fallback caso nenhum evento position chegue

function _commitPendingLoad(pos) {
  if (!_pendingLoad) return;
  const { path, paused } = _pendingLoad;
  _pendingLoad        = null;
  clearTimeout(_pendingLoadTimeout);
  _pendingLoadTimeout = null;
  loadVideo(path, pos);
  if (paused) video.addEventListener("canplay", () => video.pause(), { once: true });
}

function _cancelPendingLoad() {
  _pendingLoad        = null;
  clearTimeout(_pendingLoadTimeout);
  _pendingLoadTimeout = null;
}

(function startClock() {
  const elTime = document.getElementById("clock-time");
  const elDate = document.getElementById("clock-date");
  const days = ["Domingo","Segunda","Terça","Quarta","Quinta","Sexta","Sábado"];
  const months = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"];
  function tick() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    const ss = String(now.getSeconds()).padStart(2, "0");
    elTime.textContent = `${hh}:${mm}:${ss}`;
    elDate.textContent = `${days[now.getDay()]}, ${now.getDate()} de ${months[now.getMonth()]}`;
  }
  tick();
  setInterval(tick, 1000);
})();

function startRemainingTimer() {
  clearInterval(_remainingTimer);
  _remainingTimer = setInterval(() => updateStartTimes(), 1000);
}

function stopRemainingTimer() {
  clearInterval(_remainingTimer);
  _remainingTimer = null;
}

// Estado de reconexão do stream — controla o banner abaixo do player.
let _streamReconnecting = false;
// true somente quando o ciclo de reconexão do MPV está ativo (stream_reconnecting recebido).
// false quando o banner veio apenas do evento offline do browser (MPV ainda buffering).
let _mpvReconnectActive = false;

function _showReconnectStatus(msg) {
  _streamReconnecting = true;
  const banner = document.getElementById("reconnect-banner");
  const text   = document.getElementById("reconnect-banner-text");
  if (banner) banner.style.display = "flex";
  if (text)   text.textContent = msg;
}

function _clearReconnectStatus() {
  _streamReconnecting = false;
  _mpvReconnectActive = false;
  const banner = document.getElementById("reconnect-banner");
  if (banner) banner.style.display = "none";
}

// Detecta queda de rede via evento do browser para mostrar aviso IMEDIATAMENTE,
// sem esperar o MPV drenar o buffer (pode demorar vários segundos).
window.addEventListener("offline", () => {
  const item = state.schedule[state.currentIndex];
  if (state.playing && item?.live) {
    _showReconnectStatus("Sem conexão com a internet — aguardando rede");
    updateBadge("reconnecting");
  }
});

// Quando a rede volta: se o ciclo de reconexão do MPV ainda não iniciou
// (MPV estava buffering quando a rede caiu e voltou), limpa o banner imediatamente.
// Se o ciclo já iniciou (_mpvReconnectActive), mantém até o MPV confirmar (now_playing).
window.addEventListener("online", () => {
  if (_streamReconnecting && !_mpvReconnectActive) {
    _clearReconnectStatus();
    updateBadge("playing");
  }
});

// Eventos do servidor                                                         

function _logEvent(ev, type) {
  switch (type) {
    case "now_playing":
      log(`Reproduzindo: ${ev.item?.title || '—'}`, "now_playing"); break;
    case "paused":
      log("Reprodução pausada", "paused"); break;
    case "resumed":
      log("Reprodução retomada", "resumed"); break;
    case "stopped":
      log("Reprodução encerrada", "stopped"); break;
    case "playlist_end":
      log("Fim do roteiro", "playlist_end"); break;
    case "mpv_ready":
      log("Player pronto", "mpv_ready"); break;
    case "mpv_closed":
      log("Player encerrado", "mpv_closed"); break;
    case "stream_reconnecting":
      log(`Reconectando stream… (tentativa ${ev.attempt ?? 1})`, "stream_reconnecting"); break;
    case "stream_reconnect_failed":
      log("Falha ao reconectar o stream", "stream_reconnect_failed"); break;
  }
}

function handleEvent(ev) {
  const type = ev.event ?? "state";
  if (type !== "position") {
    _logEvent(ev, type);
  }

  switch (type) {
    case "state":
      applyState(ev);
      break;
    case "audio_level":
      _vuBackendDb = typeof ev.db === "number" ? ev.db : null;
      break;
    case "mpv_closed":
      state.mpvAlive = false;
      break;
    case "mpv_ready":
      state.mpvAlive = true;
      break;
    case "now_playing":
      _clearReconnectStatus();
      window._netMonitor?.onNowPlaying(ev.item);
      state.mpvAlive = true;
      _cancelPendingLoad();
      state.currentIndex = ev.index;
      state.playing = true;
      state.paused = false;
      state.currentItemStartTime = Date.now();
      state.pausedAt = null;
      state.totalPausedMs = 0;
      updateNowPlaying(ev.item);
      updateBadge("playing");
      highlightActive(ev.index);
      if (ev.item.live) {
        showLiveIndicator();
        if (window._setPreviewStatus) window._setPreviewStatus("Carregando live do YouTube…");
      } else if (ev.item.type === "youtube_live") {
        // Vídeo do YouTube (não ao vivo): barra de progresso via eventos MPV
        hideLiveIndicator();
        if (window._setPreviewStatus) window._setPreviewStatus(null);
        setYtVideoMode(ev.item.duration || 0);
      } else {
        hideLiveIndicator();
        if (window._setPreviewStatus) window._setPreviewStatus(null);
        _vuBackendDb = null; // volta pro analisador local — item não vem mais do YouTube
        loadVideo(ev.item.path);
      }
      updateStartTimes();
      startRemainingTimer();
      updateButtons();
      {
        const schedItem = state.schedule[ev.index];
        if (schedItem?.clip_overlays) {
          if (!_clipOverrideActive) _saveOverlayBaseline();
          _applyClipOverlays(schedItem.clip_overlays);
        } else if (_clipOverrideActive) {
          _restoreOverlayBaseline();
        }
      }
      break;
    case "paused":
      state.paused = true;
      state.pausedAt = Date.now();
      stopRemainingTimer();
      updateBadge("paused");
      updateStartTimes();
      updateButtons();
      video.pause();
      break;
    case "resumed":
      state.paused = false;
      if (state.pausedAt) {
        state.totalPausedMs += Date.now() - state.pausedAt;
        state.pausedAt = null;
      }
      updateBadge("playing");
      updateStartTimes();
      startRemainingTimer();
      updateButtons();
      video.play().catch(() => {});
      break;
    case "stopped":
      _clearReconnectStatus();
      window._netMonitor?.onStopped();
      _vuBackendDb = null;
      _cancelPendingLoad();
      state.playing = false;
      state.paused = false;
      state.currentIndex = -1;
      state.currentItemStartTime = null;
      state.pausedAt = null;
      state.totalPausedMs = 0;
      stopRemainingTimer();
      updateNowPlaying(null);
      updateBadge("stopped");
      updateButtons();
      highlightActive(-1);
      stopVideo();
      if (window._setPreviewStatus) window._setPreviewStatus(null);
      updateStartTimes();
      break;
    case "playlist_end":
      _clearReconnectStatus();
      window._netMonitor?.onStopped();
      _cancelPendingLoad();
      state.playing = false;
      state.currentItemStartTime = null;
      state.pausedAt = null;
      state.totalPausedMs = 0;
      stopRemainingTimer();
      updateBadge("stopped");
      updateNowPlaying(null);
      highlightActive(-1);
      stopVideo();
      updateStartTimes();
      updateButtons();
      break;
    case "position":
      if (_pendingLoad) _commitPendingLoad(ev.pos);
      syncPosition(ev.pos);
      break;
    case "repeat":
      state.repeat = ev.enabled;
      updateLoopIndicator();
      break;
    case "schedule_updated":
      state.schedule = ev.items ?? [];
      if (typeof ev.current_index === "number") state.currentIndex = ev.current_index;
      if (!window._schedDragging) renderSchedule();
      break;
    case "logo_list":
      updateLogoDropdowns(ev.files);
      break;
    case "logo_state":
      if (!_clipOverrideActive) applyLogoState(ev.state);
      break;
    case "text_overlay_state":
      if (!_clipOverrideActive && typeof applyTextOverlayState === "function") applyTextOverlayState(ev);
      break;
    case "stream_reconnecting": {
      const attempt = ev.attempt ?? 1;
      const max     = ev.max_attempts ?? 5;
      const delay   = ev.delay ?? 10;
      _mpvReconnectActive = true;
      let msg;
      if (ev.no_internet) {
        msg = `Sem internet — tentativa ${attempt}/${max} em ${delay}s`;
      } else if (ev.never_played) {
        msg = `Live indisponível ou não iniciada — tentativa ${attempt}/${max} em ${delay}s`;
      } else {
        msg = `Live caiu — tentativa de reconexão ${attempt}/${max} em ${delay}s`;
      }
      _showReconnectStatus(msg);
      updateBadge("reconnecting");
      break;
    }
    case "stream_reconnect_failed": {
      _clearReconnectStatus();
      let failMsg;
      if (ev.no_internet) {
        failMsg = "Sem conexão com a internet — verifique sua rede";
      } else if (ev.never_played) {
        failMsg = "Não foi possível carregar a live — verifique o link ou aguarde o início";
      } else {
        failMsg = "Falha ao reconectar a live após várias tentativas";
      }
      showToast(failMsg, "error");
      break;
    }
  }
}

function applyState(s) {
  state.currentIndex = s.index ?? -1;
  state.playing = s.running ?? false;
  state.paused = s.paused ?? false;
  if (typeof s.repeat === "boolean") { state.repeat = s.repeat; updateLoopIndicator(); }

  if (s.items) { 
    state.schedule = s.items; 
    renderSchedule(); 
  }
  
  if (s.current_item) {
    updateNowPlaying(s.current_item);
  } else {
    updateNowPlaying(null);
  }

  const _ci = s.current_item;
  if ((state.playing || state.paused) && _ci?.path && !video.src && !_ci.live) {
    if (_ci.type === "youtube_live") {
      // Vídeo YouTube: barra de progresso via eventos MPV; não carrega no elemento <video>
      setYtVideoMode(_ci.duration || 0);
    } else {
      // Adia o loadVideo até o primeiro evento "position" para usar #t=N na URL.
      // Fallback de 1.5s garante que o vídeo carregue mesmo que o evento demore.
      _pendingLoad        = { path: _ci.path, paused: state.paused };
      _pendingLoadTimeout = setTimeout(() => _commitPendingLoad(0), 5000);
    }
  }

  if (state.playing && !state.paused) {
    updateBadge("playing");
    startRemainingTimer();
  } else if (state.paused) {
    updateBadge("paused");
  } else {
    updateBadge("stopped");
  }
  updateButtons();
  highlightActive(state.currentIndex);
}

// Botões de controle de mídia

document.getElementById("btn-stop").addEventListener("click",  () => send({ action: "stop" }));
document.getElementById("btn-next").addEventListener("click",  () => send({ action: "next" }));
document.getElementById("btn-play").addEventListener("click",  () => send({ action: "play" }));
document.getElementById("btn-pause").addEventListener("click", () => send({ action: "pause" }));

// Controle de volume

const _volSlider  = document.getElementById("volume-slider");
const _volDisplay = document.getElementById("volume-db");
const _btnMute    = document.getElementById("btn-mute");
let _muted = false;

const _SVG_SPEAKER = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';
const _SVG_MUTED   = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>';
const _SVG_PLAY    = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>';
const _SVG_PAUSE   = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="3" width="4" height="18" rx="1"/><rect x="15" y="3" width="4" height="18" rx="1"/></svg>';
let _volDb = parseFloat(localStorage.getItem("playline_volume_db") ?? "0");

function _dbToMpvVol(db) {
  return Math.round(100 * Math.pow(10, db / 20));
}

function _updateFaderFill(slider) {
  const min = parseFloat(slider.min);
  const max = parseFloat(slider.max);
  const val = parseFloat(slider.value);
  const pct = ((val - min) / (max - min)) * 100;
  slider.style.background =
    `linear-gradient(to right, rgba(79,142,247,.45) ${pct}%, #22263a ${pct}%)`;
}

function _fmtDb(db) {
  const sign = db > 0 ? "+" : "";
  return sign + db.toFixed(1) + " dB";
}

// Clamp ao novo range caso localStorage tenha valor antigo fora de -10..+3
_volDb = Math.max(-20, Math.min(6, _volDb));
_volSlider.value = _volDb;
_volDisplay.textContent = _fmtDb(_volDb);
_updateFaderFill(_volSlider);

_volSlider.addEventListener("input", () => {
  _volDb = parseFloat(_volSlider.value);
  localStorage.setItem("playline_volume_db", _volDb);
  _volDisplay.textContent = _fmtDb(_volDb);
  _updateFaderFill(_volSlider);
  if (_muted) {
    _muted = false;
    _btnMute.innerHTML = _SVG_SPEAKER;
    _btnMute.classList.remove("muted");
  }
  send({ action: "set_volume", volume: _dbToMpvVol(_volDb) });
});

_btnMute.addEventListener("click", () => {
  _muted = !_muted;
  if (_muted) {
    _btnMute.innerHTML = _SVG_MUTED;
    _btnMute.classList.add("muted");
    send({ action: "set_volume", volume: 0 });
  } else {
    _btnMute.innerHTML = _SVG_SPEAKER;
    _btnMute.classList.remove("muted");
    send({ action: "set_volume", volume: _dbToMpvVol(_volDb) });
  }
});

function updateButtons() {
  const stopped = !state.playing;
  const paused  = state.paused;
  document.getElementById("btn-play").disabled = !stopped;
  document.getElementById("btn-stop").disabled = stopped;
  document.getElementById("btn-next").disabled = stopped;
  
  const btnPause = document.getElementById("btn-pause");
  btnPause.disabled    = stopped;
  btnPause.innerHTML = paused ? _SVG_PLAY : _SVG_PAUSE;
  btnPause.title       = paused ? "Retomar" : "Pausar";
}

// Lógica da Interface (Log Colapsável)                                        

const logSection = document.getElementById('log-section');
const btnToggleLog = document.getElementById('btn-toggle-log');

if (btnToggleLog && logSection) {
  btnToggleLog.addEventListener('click', () => {
    logSection.classList.toggle('collapsed');
    
    if (logSection.classList.contains('collapsed')) {
      btnToggleLog.innerHTML = '▲'; 
      btnToggleLog.title = 'Expandir';
    } else {
      btnToggleLog.innerHTML = '▼'; 
      btnToggleLog.title = 'Recolher';
    }
  });
}

// Logo overlay — dois slots com seleção estática                              

const _logoState = {
  1: { 
      corner: localStorage.getItem("playline_logo1_corner") || "br", 
      active: false, 
      filename: localStorage.getItem("playline_logo1_file") || "" 
  },
  2: { 
      corner: localStorage.getItem("playline_logo2_corner") || "bl", 
      active: false, 
      filename: localStorage.getItem("playline_logo2_file") || "" 
  },
};

// Sincroniza _logoState com o estado real do daemon (chamado ao conectar/reconectar,
// já que o daemon é um processo separado e mantém a logo ativa mesmo com a interface fechada)
function applyLogoState(remoteState) {
  if (!remoteState) return;
  [1, 2].forEach(slot => {
    const rs = remoteState[slot] ?? remoteState[String(slot)];
    if (!rs) return;
    const s = _logoState[slot];
    if (rs.active !== undefined) s.active = rs.active;
    if (rs.corner !== undefined) {
      s.corner = rs.corner;
      localStorage.setItem(`playline_logo${slot}_corner`, s.corner);
    }
    if (rs.filename) {
      s.filename = rs.filename;
      localStorage.setItem(`playline_logo${slot}_file`, s.filename);
    }
    const toggle = document.querySelector(`.btn-logo-toggle[data-slot="${slot}"]`);
    if (toggle) toggle.classList.toggle("active", s.active);
    _renderPickerDropdown(slot);
    _updateLogoOverlay(slot, s.corner, s.active);
    _updatePosSelector(slot);
  });
}

// Guarda a lista de arquivos disponíveis para uso em outros contextos
let _logoFiles = [];

function updateLogoDropdowns(files) {
  _logoFiles = files || [];
  [1, 2].forEach(slot => _renderPickerDropdown(slot));
}

function _renderPickerDropdown(slot) {
  const dropdown = document.getElementById(`logo-picker-${slot}`);
  if (!dropdown) return;

  const s = _logoState[slot];

  if (!_logoFiles.length) {
    dropdown.innerHTML = '<div class="logo-picker-empty">Pasta logos/ vazia</div>';
    return;
  }

  dropdown.innerHTML = "";
  _logoFiles.forEach(f => {
    const item = document.createElement("div");
    item.className = "logo-picker-item";

    const check = document.createElement("span");
    check.className = "logo-picker-check";
    check.textContent = s.filename === f ? "✓" : "";

    const name = document.createElement("span");
    name.className = "logo-picker-name";
    name.textContent = f;

    item.append(check, name);
    item.addEventListener("click", e => {
      e.stopPropagation();
      s.filename = f;
      localStorage.setItem(`playline_logo${slot}_file`, f);
      _renderPickerDropdown(slot);   // atualiza o ✓
      _closePicker(slot);
      if (s.active) {
        _sendLogo(slot);
        _updateLogoOverlay(slot, s.corner, s.active);
      }
    });
    dropdown.appendChild(item);
  });
}

function _closePicker(slot) {
  document.getElementById(`logo-picker-${slot}`)?.classList.remove("open");
}

function _closeAllPickers() {
  _closePicker(1);
  _closePicker(2);
}


function initLogoUI() {
  // Fecha todos os pickers ao clicar fora
  document.addEventListener("click", _closeAllPickers);

  [1, 2].forEach(slot => {
    const s        = _logoState[slot];
    const toggle   = document.querySelector(`.btn-logo-toggle[data-slot="${slot}"]`);
    const pickBtn  = document.querySelector(`.btn-logo-pick[data-slot="${slot}"]`);
    const dropdown = document.getElementById(`logo-picker-${slot}`);

    // Restaura estado visual
    if (toggle) toggle.classList.toggle("active", s.active);

    // Botão numérico "1" / "2" — toggler de ativação
    if (toggle) {
      toggle.addEventListener("click", e => {
        e.stopPropagation();
        if (!s.filename) {
          _closeAllPickers();
          dropdown?.classList.toggle("open");
          return;
        }
        s.active = !s.active;
        toggle.classList.toggle("active", s.active);
        _sendLogo(slot);
        _updateLogoOverlay(slot, s.corner, s.active);
        if (typeof _updateTextPosSelector === "function") _updateTextPosSelector();
      });
    }

    // Botão ▾ — abre/fecha picker
    if (pickBtn) {
      pickBtn.addEventListener("click", e => {
        e.stopPropagation();
        const isOpen = dropdown?.classList.contains("open");
        _closeAllPickers();
        if (!isOpen) dropdown?.classList.add("open");
      });
    }

    // Clique dentro do dropdown não propaga para fechar
    dropdown?.addEventListener("click", e => e.stopPropagation());
  });
}

function _updateLogoOverlay(slot, corner, active) {
  const el = document.getElementById(`logo-overlay-${slot}`);
  if (!el) return;
  if (active) {
    const s = _logoState[slot];
    el.src = `/api/logos/${encodeURIComponent(s.filename)}`;
    el.style.display = "";
  } else {
    el.src = "";
    el.style.display = "none";
  }
}

function _sendLogo(slot) {
  const s = _logoState[slot];
  send({
    action: "set_logo",
    slot: slot,
    filename: s.filename,
    corner: s.corner,
    active: s.active
  });
}

// ── VU Meter ─────────────────────────────────────────────────────────────────

let _vuBackendDb = null;  // nível fornecido pelo daemon (live streams)

const VU_MIN  = -40;   // dBFS mínimo do meter
const VU_MAX  =  6;    // dBFS máximo (iguala o slider)
const VU_SEGS = 30;    // nº de segmentos LED
const VU_HOLD = 1500;  // ms de peak hold antes do decay
const VU_DCY  = 0.3;   // dB/frame de decay do peak

let _vuAudioCtx = null;
let _vuAnalyser  = null;
let _vuBuf       = null;
let _vuReady     = false;
let _vuPeakDb    = VU_MIN;
let _vuPeakTil   = 0;
let _vuClipTil   = 0;

function _vuSegColor(i) {
  const p = i / VU_SEGS;
  if (p < 0.63) return { on: "#22c55e", glow: "rgba(34,197,94,.8)",  dim: "rgba(34,197,94,.07)"  };
  if (p < 0.80) return { on: "#f59e0b", glow: "rgba(245,158,11,.8)", dim: "rgba(245,158,11,.07)" };
  if (p < 0.92) return { on: "#f97316", glow: "rgba(249,115,22,.8)", dim: "rgba(249,115,22,.07)" };
  return             { on: "#ef4444", glow: "rgba(239,68,68,.9)",  dim: "rgba(239,68,68,.09)"  };
}

function _vuLed(gfx, x, y, w, h, r) {
  gfx.beginPath();
  if (gfx.roundRect) { gfx.roundRect(x, y, w, h, r); }
  else {
    const c = Math.min(r, w / 2, h / 2);
    gfx.moveTo(x + c, y);
    gfx.arcTo(x + w, y, x + w, y + h, c);
    gfx.arcTo(x + w, y + h, x, y + h, c);
    gfx.arcTo(x, y + h, x, y, c);
    gfx.arcTo(x, y, x + w, y, c);
    gfx.closePath();
  }
  gfx.fill();
}

function _vuDraw(db) {
  const canvas = document.getElementById("vu-canvas");
  if (!canvas || canvas.width === 0) return;
  const W = canvas.width, H = canvas.height;
  const gfx = canvas.getContext("2d");

  const gap  = 2;
  const r    = 2;
  const segW = Math.max(2, Math.floor((W - (VU_SEGS - 1) * gap) / VU_SEGS));
  const segH = H - 2;
  const y    = 1;

  const active  = Math.max(0, Math.min(VU_SEGS,
    Math.round((db - VU_MIN) / (VU_MAX - VU_MIN) * VU_SEGS)));
  const peakSeg = Math.min(VU_SEGS - 1,
    Math.max(0, Math.round((_vuPeakDb - VU_MIN) / (VU_MAX - VU_MIN) * VU_SEGS)));

  gfx.clearRect(0, 0, W, H);

  for (let i = 0; i < VU_SEGS; i++) {
    const c  = _vuSegColor(i);
    const x  = i * (segW + gap);
    const lit = i < active;
    if (lit) {
      gfx.shadowBlur  = 7;
      gfx.shadowColor = c.glow;
      gfx.fillStyle   = c.on;
    } else {
      gfx.shadowBlur = 0;
      gfx.fillStyle  = c.dim;
    }
    _vuLed(gfx, x, y, segW, segH, r);
  }

  // Peak hold
  if (_vuPeakDb > VU_MIN + 2) {
    const peakColor = _vuPeakDb >= 0 ? "#ef4444" : "rgba(255,255,255,.9)";
    gfx.shadowBlur  = 10;
    gfx.shadowColor = peakColor;
    gfx.fillStyle   = peakColor;
    _vuLed(gfx, peakSeg * (segW + gap), y, segW, segH, r);
  }

  gfx.shadowBlur = 0;
}

function _vuFrame() {
  requestAnimationFrame(_vuFrame);

  const canvas = document.getElementById("vu-canvas");
  if (canvas && canvas.offsetWidth > 0 && canvas.offsetWidth !== canvas.width) {
    canvas.width = canvas.offsetWidth;
  }

  let outDb;
  if (_vuBackendDb !== null) {
    // _vuBackendDb já é o nível real pós-volume do Windows Core Audio — não somar _volDb
    outDb = _muted ? VU_MIN : Math.min(VU_MAX, _vuBackendDb);
  } else if (!_vuReady || !_vuAnalyser) {
    _vuDraw(VU_MIN);
    return;
  } else {
    _vuAnalyser.getFloatTimeDomainData(_vuBuf);
    let sum = 0;
    for (let i = 0; i < _vuBuf.length; i++) sum += _vuBuf[i] * _vuBuf[i];
    const rms = Math.sqrt(sum / _vuBuf.length);
    const sigDb = 20 * Math.log10(Math.max(rms, 1e-10));
    outDb = _muted ? VU_MIN : Math.min(VU_MAX, sigDb + _volDb);
  }

  const now = performance.now();
  if (outDb > _vuPeakDb) { _vuPeakDb = outDb; _vuPeakTil = now + VU_HOLD; }
  else if (now > _vuPeakTil) _vuPeakDb = Math.max(VU_MIN, _vuPeakDb - VU_DCY);

  if (outDb >= 0) _vuClipTil = now + 2000;
  const clipEl = document.getElementById("vu-clip");
  if (clipEl) clipEl.classList.toggle("active", now < _vuClipTil);

  _vuDraw(outDb);
}

function _initVuMeter() {
  if (_vuReady) return;
  try {
    _vuAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    // createMediaElementSource toma posse do áudio: desconecta saída padrão
    const src = _vuAudioCtx.createMediaElementSource(video);
    video.muted = false; // seguro após a captura acima

    _vuAnalyser = _vuAudioCtx.createAnalyser();
    _vuAnalyser.fftSize = 2048;
    _vuAnalyser.smoothingTimeConstant = 0.1;

    const silencer = _vuAudioCtx.createGain();
    silencer.gain.value = 0; // browser fica mudo — MPV é o som real

    src.connect(_vuAnalyser);
    _vuAnalyser.connect(silencer);
    silencer.connect(_vuAudioCtx.destination);

    _vuBuf   = new Float32Array(_vuAnalyser.fftSize);
    _vuReady = true;
  } catch (e) {
    console.warn("[VU]", e);
  }
}

function _resumeVuCtx() {
  if (_vuAudioCtx && _vuAudioCtx.state === "suspended") {
    _vuAudioCtx.resume().catch(() => {});
  }
}

document.addEventListener("click",      _resumeVuCtx);
document.addEventListener("touchstart", _resumeVuCtx, { passive: true });

requestAnimationFrame(_vuFrame);

// ── Automação de overlays por clipe ──────────────────────────────────────────
// Regra: nunca modificar _logoState/_textState — estado global pertence ao operador.
// Per-clip manda comandos direto ao daemon e atualiza só o DOM de preview.

let _clipOverrideActive = false; // true = override de clipe ativo; suprime echo text_overlay_state

function _saveOverlayBaseline() {
  _clipOverrideActive = true;
}

function _restoreOverlayBaseline() {
  if (!_clipOverrideActive) return;
  _clipOverrideActive = false; // desbloqueia antes de reenviar para o echo atualizar UI se necessário
  [1, 2].forEach(slot => {
    _sendLogo(slot);
    _updateLogoOverlay(slot, _logoState[slot].corner, _logoState[slot].active);
  });
  if (typeof _sendTextOverlay === "function") _sendTextOverlay();
}

function _applyClipOverlays(co) {
  if (!co) return;

  [1, 2].forEach(slot => {
    const cfg = co[`logo${slot}`];
    if (!cfg) return;
    const s        = _logoState[slot]; // leitura apenas — não modifica
    const filename = cfg.filename !== undefined ? cfg.filename : s.filename;
    const corner   = cfg.corner   !== undefined ? cfg.corner   : s.corner;
    const active   = cfg.active   !== undefined ? cfg.active   : s.active;

    // Comando ao daemon
    send({ action: "set_logo", slot, filename, corner, active });

    // Atualiza DOM de preview sem alterar _logoState
    const el = document.getElementById(`logo-overlay-${slot}`);
    if (el) {
      if (active && filename) {
        el.src = `/api/logos/${encodeURIComponent(filename)}`;
        el.style.display = "";
      } else {
        el.src = "";
        el.style.display = "none";
      }
    }
  });

  if (co.text) {
    const active    = co.text.active    !== undefined ? co.text.active    : _textState.active;
    const show_time = co.text.show_time !== undefined ? co.text.show_time : _textState.show_time;
    const show_temp = co.text.show_temp !== undefined ? co.text.show_temp : _textState.show_temp;
    // Manda direto ao daemon — _textState e botões do painel não são tocados
    send({ action: "set_text_overlay", active, show_time, show_temp,
           corner: _textState.corner, city: _textState.city });
  }
}

// Bootstrap

async function init() {
  try {
    const res = await fetch("/api/schedule");
    state.schedule = await res.json();
    if (typeof renderSchedule === "function") renderSchedule();
  } catch (err) {}

  try {
    const res = await fetch("/api/logos");
    const data = await res.json();
    updateLogoDropdowns(data.files || []);
  } catch (err) {}

  if (typeof loadLibraryFolders === "function") loadLibraryFolders();

  initLogoUI();
  initTextOverlayUI();
  _initVuMeter();

  if (typeof connect === "function") connect();

  updateButtons();
}

init();