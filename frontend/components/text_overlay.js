/* PlayLine — text_overlay.js: controles de hora/temperatura na imagem */

// Migra cidade antiga (só "Palmas") para "Palmas,TO"
(function() {
  const saved = localStorage.getItem("playline_to_city");
  if (saved === "Palmas") localStorage.setItem("playline_to_city", "Palmas,TO");
})();

const _textState = {
  active:    false,
  show_time: true,
  show_temp: true,
  corner:    localStorage.getItem("playline_to_corner") || "tl",
  city:      localStorage.getItem("playline_to_city")   || "Palmas,TO",
};

function applyTextOverlayState(s) {
  if (s.active    !== undefined) _textState.active    = s.active;
  if (s.show_time !== undefined) _textState.show_time = s.show_time;
  if (s.show_temp !== undefined) _textState.show_temp = s.show_temp;
  if (s.corner    !== undefined) {
    _textState.corner = s.corner;
    localStorage.setItem("playline_to_corner", s.corner);
  }
  if (s.city      !== undefined) {
    const city = (s.city === "Palmas") ? "Palmas,TO" : s.city;
    _textState.city = city;
    localStorage.setItem("playline_to_city", city);
    if (city !== s.city) _sendTextOverlay();
  }
  _syncTextUI();
}

function _syncTextUI() {
  const toggle    = document.getElementById("btn-text-toggle");
  const timeCheck = document.getElementById("pick-time-check");
  const tempCheck = document.getElementById("pick-temp-check");
  const cityInp   = document.getElementById("to-city-input");

  if (toggle)    toggle.classList.toggle("active", _textState.active);
  if (timeCheck) timeCheck.style.visibility = _textState.show_time ? "" : "hidden";
  if (tempCheck) tempCheck.style.visibility = _textState.show_temp ? "" : "hidden";
  if (cityInp && document.activeElement !== cityInp) cityInp.value = _textState.city;

  _updateTextPosSelector();
  _updatePreviewOverlay();
}

function _updateTextPosSelector() {
  const selector = document.getElementById("text-pos-selector");
  if (!selector) return;

  const blocked = new Set();
  if (typeof _logoState !== "undefined") {
    [1, 2].forEach(slot => {
      if (_logoState[slot]?.active) blocked.add(_logoState[slot].corner);
    });
  }

  const corner = _textState.corner;
  selector.querySelectorAll(".pos-zone").forEach(z => {
    const c = z.dataset.corner;
    const isBlocked = blocked.has(c);
    z.classList.toggle("active",  c === corner && !isBlocked);
    z.classList.toggle("blocked", isBlocked);
    z.style.pointerEvents = isBlocked ? "none" : "";
  });

  const ind = selector.querySelector(".pos-indicator");
  if (!ind) return;
  ind.style.top    = corner[0] === "t" ? "2px" : "auto";
  ind.style.bottom = corner[0] === "b" ? "2px" : "auto";
  ind.style.left   = corner[1] === "l" ? "2px" : "auto";
  ind.style.right  = corner[1] === "r" ? "2px" : "auto";
}

function _sendTextOverlay() {
  if (typeof send === "function") {
    send({ action: "set_text_overlay", ..._textState });
  }
}

// ── Browser preview overlay ───────────────────────────────────────────────────

let _previewTemp = null;
let _previewCityFetched = "";

async function _fetchPreviewTemp() {
  const city = (_textState.city || "Palmas").split(",")[0].trim();
  try {
    const r = await fetch(`/api/temperature?city=${encodeURIComponent(city)}`);
    const t = await r.text();
    _previewTemp = t.trim() || null;
    _previewCityFetched = city;
  } catch (_) {}
}

function _updatePreviewOverlay() {
  const el = document.getElementById("text-preview-overlay");
  if (!el) return;

  if (!_textState.active) {
    el.style.display = "none";
    return;
  }

  const hasTime = _textState.show_time;
  const hasTemp = _textState.show_temp && _previewTemp;

  if (!hasTime && !hasTemp) {
    el.style.display = "none";
    return;
  }

  // Usa o canvas de preview como referência de altura (o <video> agora tem height:0)
  const previewEl = document.getElementById("mpv-preview") || document.getElementById("player-video");
  const videoH    = previewEl ? (previewEl.getBoundingClientRect().height || 200) : 200;
  el.style.fontSize = Math.max(6, Math.round(videoH * 0.020)) + "px";

  const now  = new Date();
  const hh   = String(now.getHours()).padStart(2, "0");
  const mm   = String(now.getMinutes()).padStart(2, "0");
  const ss   = String(now.getSeconds()).padStart(2, "0");
  const city = (_textState.city || "Palmas").split(",")[0].trim();

  // Layout: linha superior (to-top) com temp à esq + hora à dir; cidade abaixo
  let topEl  = el.querySelector(".to-top");
  if (!topEl) {
    topEl = document.createElement("div");
    topEl.className = "to-top";
    el.prepend(topEl);
  }

  let timeEl = topEl.querySelector(".to-time");
  let tempEl = topEl.querySelector(".to-temp");
  let cityEl = el.querySelector(".to-city-lbl");

  // Bloco temperatura — esquerda (amarelo)
  if (hasTemp) {
    if (!tempEl) {
      tempEl = document.createElement("div");
      tempEl.className = "to-temp";
      topEl.prepend(tempEl);
    }
    tempEl.textContent = _previewTemp;
  } else if (tempEl) {
    tempEl.remove();
  }

  // Bloco hora — direita (azul)
  if (hasTime) {
    if (!timeEl) {
      timeEl = document.createElement("div");
      timeEl.className = "to-time";
      topEl.appendChild(timeEl);
    }
    timeEl.textContent = `${hh}:${mm}:${ss}`;
  } else if (timeEl) {
    timeEl.remove();
  }

  // Bloco cidade — linha inteira abaixo (verde)
  if (!cityEl) {
    cityEl = document.createElement("div");
    cityEl.className = "to-city-lbl";
    el.appendChild(cityEl);
  }
  cityEl.textContent = city;

  el.className     = `text-preview-overlay corner-${_textState.corner}`;
  el.style.display = "";
}

// ── Init ──────────────────────────────────────────────────────────────────────

function initTextOverlayUI() {
  const toggle  = document.getElementById("btn-text-toggle");
  const timeBtn = document.getElementById("to-show-time-btn");
  const tempBtn = document.getElementById("to-show-temp-btn");
  const cityInp = document.getElementById("to-city-input");

  _syncTextUI();

  // Inicia clock do preview — roda sempre, _updatePreviewOverlay() verifica active
  setInterval(_updatePreviewOverlay, 1000);
  _updatePreviewOverlay();

  // Busca temperatura imediatamente e renova a cada 60s
  _fetchPreviewTemp();
  setInterval(() => {
    if (_textState.show_temp) _fetchPreviewTemp();
  }, 60000);

  if (toggle) {
    toggle.addEventListener("click", () => {
      _textState.active = !_textState.active;
      toggle.classList.toggle("active", _textState.active);
      _updatePreviewOverlay();
      _sendTextOverlay();
    });
  }

  const textPick = document.getElementById("btn-text-pick");
  const textDropdown = document.getElementById("text-picker-dropdown");

  if (textPick && textDropdown) {
    textPick.addEventListener("click", e => {
      e.stopPropagation();
      textDropdown.classList.toggle("open");
    });
    document.addEventListener("click", () => textDropdown.classList.remove("open"));
  }

  const pickTime = document.getElementById("pick-time");
  const pickTemp = document.getElementById("pick-temp");

  if (pickTime) {
    pickTime.addEventListener("click", e => {
      e.stopPropagation();
      _textState.show_time = !_textState.show_time;
      document.getElementById("pick-time-check").style.visibility = _textState.show_time ? "" : "hidden";
      _updatePreviewOverlay();
      _sendTextOverlay();
    });
  }

  if (pickTemp) {
    pickTemp.addEventListener("click", e => {
      e.stopPropagation();
      _textState.show_temp = !_textState.show_temp;
      document.getElementById("pick-temp-check").style.visibility = _textState.show_temp ? "" : "hidden";
      if (_textState.show_temp) _fetchPreviewTemp();
      _updatePreviewOverlay();
      _sendTextOverlay();
    });
  }

  if (cityInp) {
    let _cityTimer = null;
    cityInp.addEventListener("input", () => {
      const val = cityInp.value.trim();
      _textState.city = val || "Palmas";
      localStorage.setItem("playline_to_city", _textState.city);
      clearTimeout(_cityTimer);
      _cityTimer = setTimeout(() => {
        _fetchPreviewTemp();
        _sendTextOverlay();
      }, 700);
    });
  }

  document.querySelectorAll("#text-pos-selector .pos-zone").forEach(zone => {
    zone.addEventListener("click", () => {
      _textState.corner = zone.dataset.corner;
      localStorage.setItem("playline_to_corner", _textState.corner);
      _updateTextPosSelector();
      _updatePreviewOverlay();
      _sendTextOverlay();
    });
  });
}
