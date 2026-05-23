/* PlayLine — app.js: estado global, eventos do servidor e bootstrap */

const state = {
  ws: null,
  connected: false,
  schedule: [],
  currentIndex: -1,
  playing: false,
  paused: false,
  currentItemStartTime: null,
};

// ------------------------------------------------------------------ //
// Eventos do servidor                                                  //
// ------------------------------------------------------------------ //
function handleEvent(ev) {
  const type = ev.event ?? "state";
  log(JSON.stringify(ev), type);

  switch (type) {
    case "state":
      applyState(ev);
      break;
    case "now_playing":
      state.currentIndex = ev.index;
      state.playing = true;
      state.paused = false;
      state.currentItemStartTime = new Date();
      updateNowPlaying(ev.item);
      updateBadge("playing");
      highlightActive(ev.index);
      loadVideo(ev.item.path);
      updateStartTimes();
      break;
    case "paused":
      state.paused = true;
      updateBadge("paused");
      document.getElementById("btn-play").textContent = "▶";
      video.pause();
      break;
    case "resumed":
      state.paused = false;
      updateBadge("playing");
      document.getElementById("btn-play").textContent = "⏸";
      video.play().catch(() => {});
      break;
    case "stopped":
      state.playing = false;
      state.paused = false;
      state.currentIndex = -1;
      state.currentItemStartTime = null;
      updateNowPlaying(null);
      updateBadge("stopped");
      document.getElementById("btn-play").textContent = "▶";
      highlightActive(-1);
      stopVideo();
      updateStartTimes();
      break;
    case "playlist_end":
      state.playing = false;
      state.currentItemStartTime = null;
      updateBadge("stopped");
      updateNowPlaying(null);
      highlightActive(-1);
      stopVideo();
      updateStartTimes();
      break;
    case "schedule_updated":
      state.schedule = ev.items ?? [];
      renderSchedule();
      break;
  }
}

function applyState(s) {
  state.currentIndex = s.index ?? -1;
  state.playing = s.running ?? false;
  state.paused = s.paused ?? false;

  if (s.items) { state.schedule = s.items; renderSchedule(); }
  if (s.current_item) updateNowPlaying(s.current_item);
  else updateNowPlaying(null);

  if (state.playing && !state.paused) {
    updateBadge("playing");
    document.getElementById("btn-play").textContent = "⏸";
  } else if (state.paused) {
    updateBadge("paused");
    document.getElementById("btn-play").textContent = "▶";
  } else {
    updateBadge("stopped");
    document.getElementById("btn-play").textContent = "▶";
  }
  highlightActive(state.currentIndex);
}

// ------------------------------------------------------------------ //
// Botões de controle                                                   //
// ------------------------------------------------------------------ //
document.getElementById("btn-stop").addEventListener("click", () => send({ action: "stop" }));
document.getElementById("btn-next").addEventListener("click", () => send({ action: "next" }));
document.getElementById("btn-prev").addEventListener("click", () => send({ action: "prev" }));

document.getElementById("btn-play").replaceWith(
  (() => {
    const btn = document.createElement("button");
    btn.id = "btn-play";
    btn.title = "Play / Pause";
    btn.textContent = "▶";
    btn.addEventListener("click", () => {
      if (!state.playing) send({ action: "play" });
      else send({ action: "pause" });
    });
    return btn;
  })()
);

// ------------------------------------------------------------------ //
// Bootstrap                                                            //
// ------------------------------------------------------------------ //
async function init() {
  try {
    const res = await fetch("/api/schedule");
    state.schedule = await res.json();
    renderSchedule();
  } catch (_) {}

  const savedFolder = localStorage.getItem("playline_library_folder");
  if (savedFolder) {
    document.getElementById("library-folder-input").value = savedFolder;
    loadLibrary(savedFolder);
  }

  connect();
}

init();
