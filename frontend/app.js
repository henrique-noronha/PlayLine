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
};

let _remainingTimer = null;

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

// Eventos do servidor                                                         

function handleEvent(ev) {
  const type = ev.event ?? "state";
  if (type !== "position") {
    log(JSON.stringify(ev), type);
  }

  switch (type) {
    case "state":
      applyState(ev);
      break;
    case "now_playing":
      state.currentIndex = ev.index;
      state.playing = true;
      state.paused = false;
      state.currentItemStartTime = Date.now();
      state.pausedAt = null;
      state.totalPausedMs = 0;
      updateNowPlaying(ev.item);
      updateBadge("playing");
      highlightActive(ev.index);
      loadVideo(ev.item.path);
      updateStartTimes();
      startRemainingTimer();
      updateButtons();
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
      updateStartTimes();
      break;
    case "playlist_end":
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
      syncPosition(ev.pos);
      break;
    case "schedule_updated":
      state.schedule = ev.items ?? [];
      renderSchedule();
      break;
    case "logo_list":
      updateLogoDropdowns(ev.files);
      break;
  }
}

function applyState(s) {
  state.currentIndex = s.index ?? -1;
  state.playing = s.running ?? false;
  state.paused = s.paused ?? false;

  if (s.items) { 
    state.schedule = s.items; 
    renderSchedule(); 
  }
  
  if (s.current_item) {
    updateNowPlaying(s.current_item);
  } else {
    updateNowPlaying(null);
  }

  if ((state.playing || state.paused) && s.current_item?.path && !video.src) {
    loadVideo(s.current_item.path);
    if (state.paused) {
      video.addEventListener("canplay", () => video.pause(), { once: true });
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

function updateButtons() {
  const stopped = !state.playing;
  const paused  = state.paused;
  document.getElementById("btn-play").disabled = !stopped;
  document.getElementById("btn-stop").disabled = stopped;
  document.getElementById("btn-next").disabled = stopped;
  
  const btnPause = document.getElementById("btn-pause");
  btnPause.disabled    = stopped;
  btnPause.textContent = paused ? "▶" : "⏸";
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

function _updatePosSelector(slot) {
  const selector = document.querySelector(`.logo-pos-selector[data-slot="${slot}"]`);
  if (!selector) return;
  const corner = _logoState[slot].corner;

  selector.querySelectorAll(".pos-zone").forEach(z =>
    z.classList.toggle("active", z.dataset.corner === corner)
  );

  const ind = selector.querySelector(".pos-indicator");
  if (!ind) return;
  ind.style.top    = corner[0] === "t" ? "2px" : "auto";
  ind.style.bottom = corner[0] === "b" ? "2px" : "auto";
  ind.style.left   = corner[1] === "l" ? "2px" : "auto";
  ind.style.right  = corner[1] === "r" ? "2px" : "auto";
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
    _updatePosSelector(slot);

    // Zonas clicáveis do seletor visual de posição
    document.querySelectorAll(`.pos-zone[data-slot="${slot}"]`).forEach(zone => {
      zone.addEventListener("click", () => {
        s.corner = zone.dataset.corner;
        localStorage.setItem(`playline_logo${slot}_corner`, s.corner);
        _updatePosSelector(slot);
        if (s.active) {
          _sendLogo(slot);
          _updateLogoOverlay(slot, s.corner, s.active);
        }
      });
    });

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
  el.classList.remove("corner-tl", "corner-tr", "corner-bl", "corner-br");
  if (active) {
    const s = _logoState[slot];
    el.src = `/api/logos/${encodeURIComponent(s.filename)}`;
    el.classList.add(`corner-${corner}`);
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

  const savedFolder = localStorage.getItem("playline_library_folder");
  if (savedFolder) {
    const folderInput = document.getElementById("library-folder-input");
    if (folderInput) folderInput.value = savedFolder;
    if (typeof loadLibrary === "function") loadLibrary(savedFolder);
  }

  initLogoUI();

  if (typeof connect === "function") connect();

  updateButtons();
}

init();