/* PlayLine — demonstração do site: servidor e motor de vídeo simulados no navegador.

   A interface carregada em docs/demo/ é o frontend real (copiado por
   tools/demo/build_demo.py). Este arquivo roda antes dele e substitui os três
   canais que o ligam ao servidor:

     WebSocket /ws          -> FakeSocket + Engine (mesma semântica do core/playlist.py)
     WebSocket /ws/preview  -> socket que só abre; o quadro vem do motor abaixo
     fetch /api/*, /media   -> respostas no mesmo formato do api/routes.py

   O "MPV" da demo são dois <video> escondidos (atual + pré-carregado, como a
   playlist interna do MPV), desenhados no canvas #mpv-preview com o fade to
   black por cima. Nada aqui é enviado para lugar nenhum. */
(function () {
  "use strict";

  const CATALOG = window.PLAYLINE_DEMO_CATALOG || { clips: [], logos: [] };
  const BASE = "C:\\PlayLine\\Biblioteca";
  // Aberto do disco (file://) as pastas não resolvem para index.html sozinhas
  const FILE = location.protocol === "file:";
  const DEMO_URLS = FILE
    ? { site: "../index.html", download: "../index.html#download" }
    : { site: "../", download: "../#download" };
  // ?embed: prévia ao vivo dentro da página inicial do site (sem selo, links nem boas-vindas)
  const EMBED = new URLSearchParams(location.search).has("embed");

  // Idioma: sem escolha salva no navegador, segue o do visitante (o site é em português)
  const navLang = (navigator.language || "pt").toLowerCase();
  window.PLAYLINE_SERVER_LANG = navLang.startsWith("es") ? "es" : navLang.startsWith("en") ? "en" : "pt";

  const TEXT = {
    pt: {
      unavailable: "Indisponível na demonstração. Baixe o PlayLine para usar este recurso.",
      badge: "Demonstração", back: "Voltar ao site", download: "Baixar o PlayLine",
      introTitle: "Demonstração interativa",
      introBody: "Esta é a interface real do PlayLine, com vídeos e dados de exemplo. Arraste clipes da biblioteca para o roteiro, use Play, Pausa e Próximo, alterne a transição entre CUT e FTB e ligue ou desligue as logos.",
      introOk: "Começar",
    },
    en: {
      unavailable: "Not available in the demo. Download PlayLine to use this feature.",
      badge: "Demo", back: "Back to the site", download: "Download PlayLine",
      introTitle: "Interactive demo",
      introBody: "This is the real PlayLine interface with sample videos and data. Drag clips from the library into the playlist, use Play, Pause and Next, switch the transition between CUT and FTB and turn the logos on or off.",
      introOk: "Start",
    },
    es: {
      unavailable: "No disponible en la demostración. Descarga PlayLine para usar esta función.",
      badge: "Demostración", back: "Volver al sitio", download: "Descargar PlayLine",
      introTitle: "Demostración interactiva",
      introBody: "Esta es la interfaz real de PlayLine, con videos y datos de ejemplo. Arrastra clips de la biblioteca a la lista, usa Play, Pausa y Siguiente, alterna la transición entre CUT y FTB y activa o desactiva los logos.",
      introOk: "Empezar",
    },
  };
  const tx = key => {
    const lang = window.PlaylineI18n?.getLang?.() || window.PLAYLINE_SERVER_LANG;
    return (TEXT[lang] || TEXT.pt)[key];
  };

  // ── Biblioteca de exemplo ───────────────────────────────────────────────────

  const CLIPS = CATALOG.clips.map(c => ({
    ...c,
    filename: c.name + ".mp4",
    path: `${BASE}\\${c.folder}\\${c.name}.mp4`,
    file: `mock/media/${c.slug}.mp4`,
    thumb: `mock/thumbs/${c.slug}.jpg`,
  }));
  const BY_PATH = new Map(CLIPS.map(c => [c.path, c]));
  const clip = slug => CLIPS.find(c => c.slug === slug);

  function mediaFor(path) {
    const c = BY_PATH.get(path);
    return c ? c.file : "mock/media/nao-encontrado.mp4";
  }

  // O app monta URLs do servidor (/media, /api/thumbnail, /api/logos) direto em
  // src de <img>/<video>; aqui elas viram arquivos estáticos da demo.
  function mapUrl(url) {
    if (typeof url !== "string" || !url.startsWith("/")) return url;
    if (url.startsWith("/media?")) {
      const [q, hash] = url.slice(7).split("#");
      const path = new URLSearchParams(q).get("path") || "";
      return mediaFor(path) + (hash ? "#" + hash : "");
    }
    if (url.startsWith("/api/thumbnail?")) {
      const c = BY_PATH.get(new URLSearchParams(url.slice(15)).get("path") || "");
      return c ? c.thumb : "mock/thumbs/nao-encontrado.jpg";
    }
    if (url.startsWith("/api/logos/")) return "mock/logos/" + url.slice(11);
    return url;
  }

  for (const proto of [HTMLImageElement.prototype, HTMLMediaElement.prototype]) {
    const desc = Object.getOwnPropertyDescriptor(proto, "src");
    Object.defineProperty(proto, "src", {
      configurable: true,
      enumerable: desc.enumerable,
      get() { return desc.get.call(this); },
      set(v) { desc.set.call(this, mapUrl(String(v))); },
    });
  }

  // ── Utilidades ──────────────────────────────────────────────────────────────

  const pad = n => String(n).padStart(2, "0");
  const localDate = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const hms = d => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const clone = o => JSON.parse(JSON.stringify(o));
  const clamp01 = x => Math.max(0, Math.min(1, x));

  let _idSeq = 0;
  function makeItem(slug, extra = {}) {
    const c = clip(slug);
    return { id: `item-demo-${++_idSeq}`, title: c.name, path: c.path, duration: Math.round(c.duration), live: false, ...extra };
  }

  // ── Clientes WebSocket ──────────────────────────────────────────────────────

  const clients = new Set();

  function broadcast(msg) {
    const data = JSON.stringify(msg);
    clients.forEach(ws => ws._deliver(data));
  }

  const RealWebSocket = window.WebSocket;

  class FakeSocket {
    constructor(url) {
      this.url = url;
      this.readyState = FakeSocket.CONNECTING;
      this.binaryType = "blob";
      this.onopen = this.onclose = this.onmessage = this.onerror = null;
      this._preview = /\/ws\/preview/.test(url);
      setTimeout(() => {
        if (this.readyState !== FakeSocket.CONNECTING) return;
        this.readyState = FakeSocket.OPEN;
        this.onopen?.({ type: "open" });
        if (!this._preview) server.connect(this);
      }, this._preview ? 50 : 250);
    }
    _deliver(data) {
      // Ordem preservada e sempre assíncrona, como numa rede de verdade
      setTimeout(() => {
        if (this.readyState === FakeSocket.OPEN) this.onmessage?.({ data });
      }, 0);
    }
    send(raw) {
      if (this._preview || this.readyState !== FakeSocket.OPEN) return;
      try { server.command(JSON.parse(raw)); } catch (_) {}
    }
    close() {
      if (this.readyState === FakeSocket.CLOSED) return;
      this.readyState = FakeSocket.CLOSED;
      clients.delete(this);
      this.onclose?.({ code: 1000 });
    }
    addEventListener(type, fn) { this["on" + type] = fn; }
  }
  FakeSocket.CONNECTING = 0; FakeSocket.OPEN = 1; FakeSocket.CLOSING = 2; FakeSocket.CLOSED = 3;

  window.WebSocket = function (url, protocols) {
    // Em file:// o app monta "ws:///ws" (host vazio), por isso o host é opcional
    return /^wss?:\/\/[^/]*\/ws(\/preview)?(\?.*)?$/.test(String(url))
      ? new FakeSocket(String(url))
      : new RealWebSocket(url, protocols);
  };
  Object.assign(window.WebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });

  // ── Histórico (core/history.py) ─────────────────────────────────────────────

  const REASON_LABEL = { completed: "Concluído", stopped: "Parado", skipped: "Avançado", interrupted: "Interrompido", error: "Erro" };

  const history = {
    rows: [],
    current: null,
    _id: 0,
    add(date, title, path, start, end, reason, hadPause = false) {
      this.rows.push({
        id: ++this._id, date, title, path,
        started_at: hms(start), ended_at: hms(end),
        duration_played: Math.max(0, Math.round((end - start) / 1000)),
        end_reason: reason, end_reason_label: REASON_LABEL[reason] || reason, had_pause: hadPause,
      });
    },
    open(title, path) {
      this.close("interrupted");
      this.current = { title, path, start: new Date(), had_pause: false };
    },
    close(reason) {
      const c = this.current;
      if (!c) return;
      this.current = null;
      this.add(localDate(c.start), c.title, c.path, c.start, new Date(), reason, c.had_pause);
    },
    markPause() { if (this.current) this.current.had_pause = true; },
    list(date, limit) {
      const rows = date ? this.rows.filter(r => r.date === date) : this.rows;
      return rows.slice().sort((a, b) => b.id - a.id).slice(0, limit || 200);
    },
    stats() {
      const top = new Map();
      let secs = 0;
      const days = new Set();
      this.rows.forEach(r => {
        const t = top.get(r.path) || { path: r.path, title: r.title, play_count: 0, total_seconds: 0 };
        t.play_count++; t.total_seconds += r.duration_played;
        top.set(r.path, t);
        secs += r.duration_played; days.add(r.date);
      });
      const round2 = x => Math.round(x * 100) / 100;
      return {
        top_clips: [...top.values()].map(t => ({ ...t, total_hours: round2(t.total_seconds / 3600) }))
          .sort((a, b) => b.play_count - a.play_count),
        total_plays: this.rows.length,
        total_hours: round2(secs / 3600),
        total_days: days.size,
        by_date: [],
      };
    },
  };

  // Semana anterior de exibições: a mesma grade rodando em loop por um trecho do dia
  function seedHistory(schedule) {
    const loopFrom = (startMs, endMs) => {
      let t = startMs, i = 0, n = 0;
      while (t < endMs) {
        const it = schedule[i % schedule.length];
        const dur = (it.end_time || it.duration) * 1000;
        const end = new Date(Math.min(t + dur, endMs));
        const skipped = n > 0 && n % 37 === 0;
        const realEnd = skipped ? new Date(t + dur * 0.6) : end;
        history.add(localDate(new Date(t)), it.title, it.path, new Date(t), realEnd, skipped ? "skipped" : "completed", n % 53 === 0 && n > 0);
        t = realEnd.getTime(); i++; n++;
      }
    };
    const now = new Date();
    for (let d = 6; d >= 1; d--) {
      const day = new Date(now); day.setDate(now.getDate() - d); day.setHours(18, 0, 0, 0);
      loopFrom(day.getTime(), day.getTime() + 55 * 60 * 1000);
      const last = history.rows[history.rows.length - 1];
      if (last) { last.end_reason = "stopped"; last.end_reason_label = REASON_LABEL.stopped; }
    }
    loopFrom(now.getTime() - 25 * 60 * 1000, now.getTime() - 1000);
  }

  // ── "MPV": dois <video> alternados, desenhados no canvas do preview ─────────

  const mpv = {
    els: [],
    cur: null,
    nxt: null,
    item: null,
    onAir: false,
    paused: false,
    fadeIn: false,
    manualOutAt: null,
    pending: null,
    endedFired: false,
    volume: 100,
    lastPosAt: 0,

    init() {
      const wrap = document.querySelector(".player-wrap");
      for (let i = 0; i < 2; i++) {
        const v = document.createElement("video");
        v.muted = true;
        v.playsInline = true;
        v.preload = "auto";
        v.className = "demo-mpv";
        v.setAttribute("aria-hidden", "true");
        // Fica dentro do preview (atrás do canvas): o Chrome pausa vídeo mudo fora da tela
        (wrap || document.body).appendChild(v);
        v.addEventListener("ended", () => { if (v === this.cur) this._eof(); });
        v.addEventListener("error", () => {
          if (v === this.cur && this.onAir && !this.endedFired) { this.endedFired = true; engine.onEndFile("error"); }
        });
        this.els.push(v);
      }
      [this.cur, this.nxt] = this.els;
      this.canvas = document.getElementById("mpv-preview");
      this.ctx = this.canvas?.getContext("2d");
      this.overlays = () => document.querySelectorAll(".player-wrap .logo-overlay, #text-preview-overlay");
      setInterval(() => this._tick(), 100);
      const loop = () => { this._draw(); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    },

    _fadeDur() { return engine.transition.duration || 0.5; },

    // Tempo do clipe e fim efetivo (recorte de fim, se houver)
    _times() {
      const v = this.cur, it = this.item || {};
      const start = it.start_time > 0 ? it.start_time : 0;
      const end = it.end_time > 0 ? it.end_time : (isFinite(v.duration) ? v.duration : Infinity);
      return { t: v.currentTime, start, end };
    },

    alpha() {
      if (!this.onAir) return 0;
      const d = this._fadeDur();
      let a = 0;
      if (this.manualOutAt != null) a = clamp01((performance.now() - this.manualOutAt) / (d * 1000));
      const { t, start, end } = this._times();
      if (this.fadeIn && t - start < d) a = Math.max(a, 1 - (t - start) / d);
      if (engine.boundaryTransition() === "fade" && isFinite(end) && end - t < d) a = Math.max(a, 1 - (end - t) / d);
      return clamp01(a);
    },

    play(item, trans) {
      clearTimeout(this.pending);
      if (this.onAir && trans === "fade" && this.alpha() < 0.99) {
        this.manualOutAt = performance.now();
        this.pending = setTimeout(() => this._switch(item, trans), this._fadeDur() * 1000);
      } else {
        this._switch(item, trans);
      }
    },

    _switch(item, trans) {
      this.manualOutAt = null;
      const file = mediaFor(item.path);
      if (this.nxt.dataset.file === file && this.cur.dataset.file !== file) {
        [this.cur, this.nxt] = [this.nxt, this.cur];
      } else if (this.cur.dataset.file !== file) {
        this.cur.dataset.file = file;
        this.cur.src = file;
      }
      this.nxt.pause();
      const start = item.start_time > 0 ? item.start_time : 0;
      try { this.cur.currentTime = start; } catch (_) {}
      this.item = item;
      this.onAir = true;
      this.paused = false;
      this.fadeIn = trans === "fade";
      this.endedFired = false;
      this.cur.play().catch(() => {});
    },

    preload(item) {
      if (!item) return;
      const file = mediaFor(item.path);
      if (this.nxt.dataset.file === file) return;
      this.nxt.dataset.file = file;
      this.nxt.src = file;
      this.nxt.load();
    },

    pause() { this.paused = true; this.cur.pause(); },
    resume() { this.paused = false; if (this.onAir) this.cur.play().catch(() => {}); },

    stop(trans) {
      clearTimeout(this.pending);
      const done = () => {
        this.onAir = false;
        this.item = null;
        this.manualOutAt = null;
        this.els.forEach(v => v.pause());
        this.overlays().forEach(el => { el.style.opacity = ""; });
        window._setPreviewStatus?.(null);   // volta o "Aguardando sinal" do app
      };
      if (this.onAir && trans === "fade" && !this.paused) {
        this.manualOutAt = performance.now();
        this.pending = setTimeout(done, this._fadeDur() * 1000);
      } else {
        done();
      }
    },

    position() { return this.onAir ? Math.round(this.cur.currentTime * 100) / 100 : 0; },

    _eof() {
      if (!this.onAir || this.endedFired) return;
      this.endedFired = true;
      engine.onEndFile("eof");
    },

    _tick() {
      if (!this.onAir || this.paused || this.manualOutAt != null) return;
      const { t, end } = this._times();
      if (isFinite(end) && t >= end - 0.05) { this._eof(); return; }
      const now = performance.now();
      if (now - this.lastPosAt >= 500 && this.cur.readyState >= 2) {
        this.lastPosAt = now;
        engine.onPosition(this.position());
      }
    },

    _draw() {
      if (!this.onAir || !this.ctx) return;
      const v = this.cur, c = this.canvas;
      if (v.readyState >= 2) this.ctx.drawImage(v, 0, 0, c.width, c.height);
      const a = this.alpha();
      if (a > 0) {
        this.ctx.fillStyle = `rgba(0,0,0,${a})`;
        this.ctx.fillRect(0, 0, c.width, c.height);
      }
      // O preto do FTB fica acima das logos e do texto, como no MPV
      const op = a > 0 ? String(1 - a) : "";
      this.overlays().forEach(el => { if (el.style.opacity !== op) el.style.opacity = op; });
    },
  };

  // ── Motor do roteiro (core/playlist.py:PlaylistEngine) ──────────────────────

  const engine = {
    items: [],
    index: -1,
    running: false,
    paused: false,
    repeat: true,
    transition: { type: "cut", duration: 0.5 },
    advanceSeq: 0,
    lastPosition: 0,
    logo: {
      "1": { active: true, filename: "PlayLine TV.png", corner: "tr" },
      "2": { active: false, filename: "Classificação livre.png", corner: "bl" },
    },
    text: { active: true, show_time: true, show_temp: true, corner: "tl", city: "Palmas,TO", manual_temp: "" },

    state() {
      const item = this.items[this.index] || null;
      return {
        event: "state", running: this.running, paused: this.paused, index: this.index,
        current_item: item, total_items: this.items.length, repeat: this.repeat,
        position: this.running ? mpv.position() : 0, transition: { ...this.transition },
      };
    },

    transitionInto(item) { return (item && (item.transition === "fade" || item.transition === "cut")) ? item.transition : this.transition.type; },

    nextItem() {
      if (this.index < 0 || !this.items.length) return null;
      if (this.index + 1 < this.items.length) return this.items[this.index + 1];
      return this.repeat ? this.items[0] : null;
    },

    // Transição da próxima fronteira (fade out automático antes do fim do clipe)
    boundaryTransition() {
      if (!this.running) return "cut";
      return this.transitionInto(this.nextItem());
    },

    _fillDurations(items) {
      items.forEach(it => {
        if (!(it.duration > 0) && BY_PATH.has(it.path)) it.duration = Math.round(BY_PATH.get(it.path).duration);
      });
      return items;
    },

    saveSchedule(items) {
      const curId = this.index >= 0 ? this.items[this.index]?.id : null;
      this.items = this._fillDurations(items);
      if (curId) {
        const idx = this.items.findIndex(it => it.id === curId);
        if (idx >= 0) this.index = idx;
      }
      if (this.running) mpv.preload(this.nextItem());
    },

    playIndex(index) {
      if (!(index >= 0 && index < this.items.length)) return;
      this.index = index;
      this.running = true;
      this.paused = false;
      this.lastPosition = 0;
      const item = this.items[index];
      history.open(item.title || item.path.split("\\").pop(), item.path);
      mpv.play(item, this.transitionInto(item));
      mpv.preload(this.nextItem());
      broadcast({ event: "now_playing", index, item });
    },

    play() { this.advanceSeq++; this.playIndex(0); },

    pauseToggle() {
      if (!this.running) return;
      this.paused = !this.paused;
      if (this.paused) { history.markPause(); mpv.pause(); broadcast({ event: "paused" }); }
      else { mpv.resume(); broadcast({ event: "resumed" }); }
    },

    stop() {
      this.advanceSeq++;
      const wasOnAir = this.running;
      this.running = false; this.paused = false; this.index = -1;
      history.close("stopped");
      mpv.stop(wasOnAir ? this.transition.type : "cut");
      broadcast({ event: "stopped" });
    },

    next() { history.close("skipped"); this.advance(-1); },

    advance(expectedSeq = -1) {
      if (expectedSeq >= 0 && expectedSeq !== this.advanceSeq) return;
      this.advanceSeq++;
      if (this.repeat) {
        if (!this.items.length) return;
        const next = this.index + 1 >= this.items.length ? 0 : this.index + 1;
        this.playIndex(next);
        return;
      }
      if (this.items.length) this.items.shift();
      broadcast({ event: "schedule_updated", items: clone(this.items) });
      if (this.items.length) {
        this.playIndex(0);
      } else {
        this.running = false; this.index = -1;
        mpv.stop("cut");
        broadcast({ event: "playlist_end" });
      }
    },

    jump(index) {
      if (!(index >= 0 && index < this.items.length)) return;
      this.advanceSeq++;
      if (!this.repeat && index > 0) {
        this.items.splice(0, index);
        broadcast({ event: "schedule_updated", items: clone(this.items) });
        index = 0;
      }
      this.playIndex(index);
    },

    onEndFile(reason) {
      history.close(reason === "error" ? "error" : "completed");
      if (this.running) {
        const seq = this.advanceSeq;
        setTimeout(() => this.advance(seq), 0);
      }
    },

    onPosition(pos) {
      this.lastPosition = pos;
      broadcast({ event: "position", pos });
    },

    setRepeat(enabled) {
      const previously = this.repeat;
      this.repeat = enabled;
      if (!enabled && previously && this.index > 0 && this.index < this.items.length) {
        this.items = this.items.slice(this.index);
        this.index = 0;
        broadcast({ event: "schedule_updated", items: clone(this.items), current_index: 0 });
      }
      if (this.running) mpv.preload(this.nextItem());
      broadcast({ event: "repeat", enabled });
    },

    setTransition(cfg) {
      if (cfg.type !== undefined) {
        if (cfg.type !== "cut" && cfg.type !== "fade") throw new Error("tipo inválido");
        this.transition.type = cfg.type;
      }
      if (cfg.duration !== undefined) {
        const d = Number(cfg.duration);
        if (!(d >= 0.2 && d <= 3)) throw new Error("duração inválida");
        this.transition.duration = Math.round(d * 100) / 100;
      }
      broadcast({ event: "transition_state", transition: { ...this.transition } });
      return { ...this.transition };
    },
  };

  // ── Medidor de áudio (o daemon mede o som real; aqui é um nível plausível) ──

  let vuLevel = -14;
  setInterval(() => {
    if (!engine.running) return;
    if (engine.paused || mpv.volume <= 0 || mpv.alpha() > 0.98) { broadcast({ event: "audio_level", db: -90 }); return; }
    vuLevel += (Math.random() - 0.5) * 5 + (-13 - vuLevel) * 0.25;
    const gain = 20 * Math.log10(mpv.volume / 100);
    const faded = 20 * Math.log10(Math.max(0.001, 1 - mpv.alpha()));
    broadcast({ event: "audio_level", db: Math.round((vuLevel + gain + faded) * 10) / 10 });
  }, 80);

  // ── Servidor: comandos do /ws (api/websocket.py) ────────────────────────────

  const server = {
    connect(ws) {
      clients.add(ws);
      ws._deliver(JSON.stringify(engine.state()));
      ws._deliver(JSON.stringify({ event: "logo_list", files: CATALOG.logos }));
      ws._deliver(JSON.stringify({ event: "logo_state", state: clone(engine.logo) }));
      ws._deliver(JSON.stringify({ event: "text_overlay_state", ...engine.text }));
    },
    command(cmd) {
      switch (cmd.action) {
        case "play": engine.play(); break;
        case "pause": engine.pauseToggle(); break;
        case "stop": engine.stop(); break;
        case "next": engine.next(); break;
        case "jump": engine.jump(cmd.index || 0); break;
        case "state": broadcast(engine.state()); break;
        case "set_volume": mpv.volume = Math.max(0, Math.min(200, Number(cmd.volume) || 0)); break;
        case "set_transition":
          try { engine.setTransition({ type: cmd.type, duration: cmd.duration }); } catch (_) {}
          break;
        case "set_logo": {
          const s = engine.logo[String(cmd.slot)];
          if (!s) break;
          s.corner = cmd.corner || "br";
          s.active = !!cmd.active;
          if (cmd.filename) s.filename = cmd.filename;
          broadcast({ event: "logo_state", state: clone(engine.logo) });
          break;
        }
        case "set_text_overlay":
          Object.assign(engine.text, {
            active: !!cmd.active, show_time: cmd.show_time !== false, show_temp: cmd.show_temp !== false,
            corner: String(cmd.corner || "tl"), city: String(cmd.city || "Palmas,TO"), manual_temp: String(cmd.manual_temp || ""),
          });
          broadcast({ event: "text_overlay_state", ...engine.text });
          break;
      }
    },
  };

  // ── Servidor: HTTP (api/routes.py) ──────────────────────────────────────────

  const CITIES = [
    { name: "Palmas", state: "TO", lat: -10.18, lon: -48.33, temp: "34°C" },
    { name: "Araguaína", state: "TO", lat: -7.19, lon: -48.21, temp: "33°C" },
    { name: "Gurupi", state: "TO", lat: -11.73, lon: -49.07, temp: "35°C" },
    { name: "Brasília", state: "DF", lat: -15.79, lon: -47.88, temp: "27°C" },
    { name: "Goiânia", state: "GO", lat: -16.68, lon: -49.25, temp: "31°C" },
    { name: "São Paulo", state: "SP", lat: -23.55, lon: -46.63, temp: "22°C" },
  ];

  const saved = [];
  let savedSeq = 0;
  function addSaved(title, items, minutesAgo) {
    const d = new Date(Date.now() - minutesAgo * 60000);
    saved.push({ id: ++savedSeq, title, created_at: `${localDate(d)}T${hms(d)}`, items: clone(items) });
  }

  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const unavailable = () => json({ detail: tx("unavailable"), error: tx("unavailable") }, 403);

  async function readBody(init) {
    try { return init && init.body ? JSON.parse(init.body) : {}; } catch (_) { return {}; }
  }

  async function api(url, init = {}) {
    const u = new URL(url, "http://demo.local");   // location.origin é "null" em file://
    const p = u.pathname, q = u.searchParams;
    const method = (init.method || "GET").toUpperCase();

    if (p === "/api/schedule") {
      if (method === "PUT") {
        const items = await readBody(init);
        engine.saveSchedule(Array.isArray(items) ? items : []);
        broadcast({ event: "schedule_updated", items: clone(engine.items) });
        return json({ ok: true });
      }
      return json(clone(engine.items));
    }
    if (p === "/api/state") return json(engine.state());
    if (p === "/api/logos") return json({ files: CATALOG.logos });
    if (p === "/api/library") {
      return json({ subfolders: [...new Set(CLIPS.map(c => c.folder))].sort((a, b) => a.localeCompare(b)), base: BASE });
    }
    if (p === "/api/library/files") {
      const sub = q.get("subfolder") || "";
      const files = CLIPS.filter(c => !sub || c.folder === sub)
        .map(c => ({ name: c.name, filename: c.filename, path: c.path }));
      if (sub && !files.length) return json({ detail: "Pasta não encontrada" }, 404);
      if (!sub) files.sort((a, b) => a.filename.toLowerCase().localeCompare(b.filename.toLowerCase()));
      return json({ files });
    }
    if (p === "/api/temperature") {
      const name = (q.get("city") || "Palmas").split(",")[0].trim().toLowerCase();
      const c = CITIES.find(x => x.name.toLowerCase() === name);
      return new Response(c ? c.temp : "30°C", { headers: { "Content-Type": "text/plain" } });
    }
    if (p === "/api/cities") {
      if (method === "PUT") return unavailable();
      return json({ cities: CITIES.map(({ temp, ...c }) => c), max: 30 });
    }
    if (p === "/api/settings") {
      return json({
        username: "playline", library_dir: BASE, library_default: BASE,
        library_configured: "", library_missing: false, transition: { ...engine.transition },
      });
    }
    if (p === "/api/settings/transition") {
      const body = await readBody(init);
      try {
        return json({ ok: true, transition: engine.setTransition({ type: body.type, duration: body.duration }) });
      } catch (e) {
        return json({ detail: "A duração do FTB deve ficar entre 0,2 e 3 segundos" }, 400);
      }
    }
    if (p === "/api/settings/language") return json({ ok: true });
    if (p === "/api/history") return json({ entries: history.list(q.get("date") || "", Number(q.get("limit")) || 200) });
    if (p === "/api/history/stats") return json(history.stats());
    if (p === "/api/repeat") {
      const body = await readBody(init);
      engine.setRepeat(!!body.enabled);
      return json({ repeat: !!body.enabled });
    }
    if (p === "/api/saved-schedules") {
      if (method === "POST") {
        const body = await readBody(init);
        const title = String(body.title || "").trim();
        if (!title) return json({ detail: "Título obrigatório", code: "schedule_title_required" }, 400);
        addSaved(title, body.items || [], 0);
        return json({ id: savedSeq });
      }
      return json({
        schedules: saved.slice().sort((a, b) => b.created_at.localeCompare(a.created_at))
          .map(s => ({ id: s.id, title: s.title, created_at: s.created_at, item_count: s.items.length })),
      });
    }
    let m = p.match(/^\/api\/saved-schedules\/(\d+)(\/items)?$/);
    if (m) {
      const idx = saved.findIndex(s => s.id === Number(m[1]));
      if (idx < 0) return json({ detail: "Roteiro não encontrado" }, 404);
      if (method === "DELETE") { saved.splice(idx, 1); return json({ ok: true }); }
      return json({ items: clone(saved[idx].items) });
    }
    if (p === "/api/validate-paths") {
      const body = await readBody(init);
      return json({ missing: (body.paths || []).filter(x => !BY_PATH.has(x)) });
    }
    if (p === "/api/capture-devices") return json({ devices: [] });
    // Pasta da biblioteca, usuário e senha, busca de cidades, YouTube, upload, pastas
    if (p.startsWith("/api/")) return unavailable();
    return json({ detail: "Não encontrado" }, 404);
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : input?.url || "";
    if (url.startsWith("/api/")) {
      return new Promise(r => setTimeout(r, 30)).then(() => api(url, init || {}));
    }
    return realFetch(input, init);
  };

  // ── Grade inicial ───────────────────────────────────────────────────────────

  const START = [
    makeItem("vinheta-abertura"),
    makeItem("jornal-bloco-1"),
    makeItem("vinheta-intervalo"),
    makeItem("campanha-vacinacao", { transition: "fade" }),
    makeItem("previsao-do-tempo"),
    makeItem("chamada-cidadania"),
    makeItem("jornal-bloco-2", { end_time: 18 }),
    makeItem("transparencia-publica", {
      clip_overlays: {
        logo1: { active: false, filename: "PlayLine TV.png", corner: "tr" },
        logo2: { active: true, filename: "Classificação livre.png", corner: "bl" },
        text: { active: false, show_time: true, show_temp: true },
      },
    }),
    makeItem("chamada-sessao", { transition: "fade" }),
  ];
  engine.items = clone(START);
  seedHistory(START);
  addSaved("Grade da manhã", [
    makeItem("vinheta-abertura"), makeItem("jornal-bloco-1"), makeItem("previsao-do-tempo"),
    makeItem("campanha-vacinacao"), makeItem("jornal-bloco-2"),
  ], 60 * 26);
  addSaved("Especial Cidadania", [
    makeItem("chamada-cidadania"), makeItem("transparencia-publica"), makeItem("chamada-sessao"),
  ], 60 * 3);

  // ── Elementos só da demo: selo, links e boas-vindas ─────────────────────────

  const BLOCKED = "#btn-capture-open, #btn-yt-open, #iq-btn-camera, #iq-btn-youtube, #iq-btn-add";
  document.addEventListener("click", e => {
    if (!e.target.closest?.(BLOCKED)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    window.showToast?.(tx("unavailable"), "info");
  }, true);

  function decorate() {
    const header = document.querySelector("header");
    if (header && !header.querySelector(".demo-bar")) {
      const bar = document.createElement("div");
      bar.className = "demo-bar";
      bar.innerHTML =
        `<span class="demo-badge">${tx("badge")}</span>` +
        `<a class="demo-link" href="${DEMO_URLS.site}">${tx("back")}</a>` +
        `<a class="demo-link demo-link-cta" href="${DEMO_URLS.download}">${tx("download")}</a>`;
      header.insertBefore(bar, header.querySelector(".conn-status"));
    }
    let seen = false;
    try { seen = sessionStorage.getItem("playline_demo_intro") === "1"; } catch (_) {}
    if (!seen) {
      const card = document.createElement("div");
      card.className = "demo-intro";
      card.setAttribute("role", "dialog");
      card.innerHTML = `<strong>${tx("introTitle")}</strong><p>${tx("introBody")}</p><button type="button">${tx("introOk")}</button>`;
      card.querySelector("button").addEventListener("click", () => {
        card.remove();
        try { sessionStorage.setItem("playline_demo_intro", "1"); } catch (_) {}
      });
      document.body.appendChild(card);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    mpv.init();
    if (EMBED) document.documentElement.classList.add("demo-embed");
    else decorate();
    engine.play();   // a emissora já está no ar quando a página abre
  });
})();
