/* PlayLine — WebSocket: conexão e reconexão */

const WS_URL = `ws://${location.host}/ws`;

function connect() {
  setConnStatus("connecting");
  state.ws = new WebSocket(WS_URL);

  state.ws.onopen = () => {
    state.connected = true;
    setConnStatus("connected");
    log("Conectado ao servidor", "info");
  };

  state.ws.onclose = async () => {
    state.connected = false;
    setConnStatus("disconnected");

    // Para o timer de posição e congela a UI até o servidor responder.
    // applyState() restaura o estado correto ao reconectar.
    state.playing = false;
    state.paused  = false;
    stopRemainingTimer();
    stopVideo();
    updateBadge("stopped");
    updateButtons();

    // O /ws exige sessão válida; sem ela o servidor rejeita o handshake com
    // HTTP 403, que aqui chega como um close 1006 idêntico a queda de rede.
    // Distingue os dois casos antes de entrar em loop de reconexão a cada 3s.
    if (await _sessionExpired()) {
      log("Sessão expirada. Faça login novamente.", "error");
      location.href = "/login";
      return;
    }
    log("Conexão perdida. Reconectando em 3s…", "error");
    setTimeout(connect, 3000);
  };

  state.ws.onerror = () => log("Falha na conexão com o servidor", "error");

  state.ws.onmessage = (e) => {
    try { handleEvent(JSON.parse(e.data)); }
    catch (err) { log("Erro ao processar mensagem do servidor", "error"); }
  };
}

// true se o servidor está de pé mas recusa a sessão (redirect para /login ou 401).
// Servidor fora do ar (fetch lança) NÃO conta como sessão expirada.
async function _sessionExpired() {
  try {
    const r = await fetch("/api/schedule", { redirect: "manual", cache: "no-store" });
    return r.type === "opaqueredirect" || r.status === 302 || r.status === 401;
  } catch (_) {
    return false;
  }
}

function send(cmd) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN)
    state.ws.send(JSON.stringify(cmd));
}
