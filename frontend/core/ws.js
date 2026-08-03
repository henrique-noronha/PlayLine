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

  state.ws.onclose = () => {
    state.connected = false;
    setConnStatus("disconnected");
    log("Conexão perdida. Reconectando em 3s…", "error");
    setTimeout(connect, 3000);
  };

  state.ws.onerror = () => log("Falha na conexão com o servidor", "error");

  state.ws.onmessage = (e) => {
    try { handleEvent(JSON.parse(e.data)); }
    catch (err) { log("Erro ao processar mensagem do servidor", "error"); }
  };
}

function send(cmd) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN)
    state.ws.send(JSON.stringify(cmd));
}
