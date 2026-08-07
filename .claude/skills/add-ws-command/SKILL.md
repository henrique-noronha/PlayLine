# Skill: add-ws-command

## Quando usar
Sempre que precisar adicionar um comando que o **frontend envia para o backend** via WebSocket em tempo real.
Diferente de eventos (backend → frontend), comandos seguem o sentido inverso: frontend → backend.
Use quando a tarefa envolver "botão que aciona algo", "controle em tempo real" ou "ação sem recarregar página".

## Diferença entre comando e evento

| | Comando WS | Evento WS |
|---|---|---|
| Direção | Frontend → Backend | Backend → Frontend |
| Quando usar | Usuário aciona uma ação | Sistema notifica a UI |
| Arquivo backend | `api/websocket.py` | `core/playlist.py` + `app.js` |
| Skill | `/add-ws-command` | `/add-event` |

---

## Passo a passo

### 1. Frontend — enviar o comando

Em qualquer componente JS, usando `state.ws`:

```js
// Comando simples
state.ws.send(JSON.stringify({ action: "nome_acao" }));

// Comando com dados
state.ws.send(JSON.stringify({
  action: "nome_acao",
  campo: valor,
  outro: valor2,
}));
```

Sempre verificar se o WebSocket está aberto antes de enviar:
```js
if (state.ws && state.ws.readyState === WebSocket.OPEN) {
  state.ws.send(JSON.stringify({ action: "nome_acao" }));
}
```

---

### 2. Backend — receber em websocket.py

Em `_handle_command()`, adicionar um `elif` no bloco existente:

```python
async def _handle_command(cmd: dict):
    action = cmd.get("action")
    ...
    elif action == "nome_acao":
        campo = cmd.get("campo")
        await _playlist_engine.metodo_correspondente(campo)
```

**O nome do `action` deve ser idêntico** ao enviado pelo frontend.

---

### 3. playlist.py ou player.py — implementar a lógica

Se a ação envolve reprodução/roteiro, adicionar método em `PlaylistEngine`:

```python
async def metodo_correspondente(self, campo):
    # lógica aqui
    await self._broadcast({"event": "resultado_evento", "campo": campo})
```

Se envolve controle direto do MPV (volume, seek, logo), delegar para `self._player`:
```python
async def metodo_correspondente(self, valor):
    self._player.algum_metodo(valor)
```

---

## Checklist

- [ ] `action` é uma string única, sem conflito com os existentes
- [ ] Frontend usa `state.ws.send(JSON.stringify({action: "...", ...}))`
- [ ] `elif action == "nome_acao":` adicionado em `_handle_command` em `websocket.py`
- [ ] Lógica implementada em `playlist.py` ou delegada para `player.py`
- [ ] Se gera resposta visível: emite evento de volta via `self._broadcast`

## Referência — comandos existentes

| action | O que faz |
|--------|-----------|
| `play` | Inicia reprodução pelo primeiro item |
| `pause` | Alterna pausa/reprodução |
| `stop` | Para tudo |
| `next` | Avança para o próximo item |
| `jump` | Pula para índice N (`index: N`) |
| `set_volume` | Define volume (`volume: 0-200`) |
| `set_logo` | Configura logo overlay (`slot, filename, corner, active`) |
| `set_text_overlay` | Configura overlay de texto/temperatura |
| `reload_schedule` | Recarrega roteiro do banco |
| `state` | Solicita estado atual da engine |