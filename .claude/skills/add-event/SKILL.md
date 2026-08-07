# Skill: add-event

## Quando usar
Sempre que precisar propagar um novo evento em tempo real pelo sistema — do MPV até o frontend.
Use antes de tocar qualquer arquivo quando a tarefa envolver "emitir", "notificar", "broadcast" ou "detectar" algo novo.

## Arquitetura do fluxo de eventos

O PlayLine tem uma cadeia rígida de 5 camadas. Todo evento percorre esse caminho de cima para baixo:

```
[MPV process]
     ↓  callback Python registrado via @mpv.event_callback
[daemon/daemon.py]  →  _broadcast_sync({"event": "nome"})
     ↓  TCP 127.0.0.1:6600 (JSON por linha)
[core/player.py]   →  _handle_event  →  chama self._on_nome()
     ↓  callback definido em main.py
[main.py]          →  def _on_nome(): playlist_engine.on_nome()
     ↓  ou broadcast direto via asyncio.run_coroutine_threadsafe
[core/playlist.py] →  async def on_nome() ou dentro de outro método
     ↓  WebSocket JSON
[frontend/app.js]  →  case "nome": no handleEvent()
```

Eventos que **não vêm do MPV** (ex: lógica da engine) entram na cadeia a partir de `playlist.py`, pulando as duas primeiras camadas.

---

## Passo a passo

### 1. daemon/daemon.py — emitir o evento

Dentro do callback `@self._mpv.event_callback("alguma-coisa")` ou em qualquer ponto do daemon:

```python
self._broadcast_sync({"event": "nome_do_evento", "campo": valor})
```

`_broadcast_sync` é thread-safe — pode ser chamado de callbacks MPV (que rodam em thread separada).

**Exemplo real** — evento `file-loaded` adicionado para reconexão de live:
```python
@self._mpv.event_callback("file-loaded")
def _file_loaded(event):
    # ... lógica existente ...
    self._broadcast_sync({"event": "file-loaded"})
```

Se o evento **não vem do MPV**, pule esta etapa.

---

### 2. core/player.py — receber e repassar via callback

**2a. Declarar o callback no `__init__`:**
```python
def __init__(self, ..., on_nome: Optional[Callable[[], None]] = None):
    ...
    self._on_nome = on_nome
```

**2b. Tratar o evento em `_handle_event`:**
```python
def _handle_event(self, msg: dict):
    event = msg.get("event")
    ...
    elif event == "nome_do_evento":
        if self._on_nome:
            self._on_nome()
```

Se o evento carregar dados, passe-os como argumento: `self._on_nome(msg.get("campo"))`.

**Exemplo real** — callback `on_file_loaded`:
```python
elif event == "file-loaded":
    if self._on_file_loaded:
        self._on_file_loaded()
```

---

### 3. main.py — definir o callback e conectar

Dentro de `lifespan()`, antes da criação do `Player`:

```python
def _on_nome():
    if playlist_engine:
        playlist_engine.on_nome()
    # ou broadcast direto:
    # asyncio.run_coroutine_threadsafe(
    #     manager.broadcast({"event": "nome_do_evento"}), loop
    # )

player_instance = Player(
    ...
    on_nome=_on_nome,
)
```

**Exemplo real:**
```python
def _on_file_loaded():
    if playlist_engine:
        playlist_engine.on_file_loaded()

player_instance = Player(
    on_end_file=_on_end,
    ...
    on_file_loaded=_on_file_loaded,
)
```

---

### 4. core/playlist.py — reagir e fazer broadcast para o frontend

```python
def on_nome(self):
    """Chamado pelo Player quando o MPV sinaliza nome_do_evento."""
    # lógica de negócio aqui
    # para emitir pro frontend:
    if self._loop:
        asyncio.run_coroutine_threadsafe(
            self._broadcast({"event": "nome_do_evento", "campo": valor}),
            self._loop
        )
```

Se a reação for assíncrona:
```python
def on_nome(self):
    if self._loop:
        asyncio.run_coroutine_threadsafe(self._handle_nome(), self._loop)

async def _handle_nome(self):
    await self._broadcast({"event": "nome_do_evento"})
```

**Atenção:** `on_nome()` é chamado da thread de leitura TCP do Player — nunca use `await` diretamente. Sempre use `asyncio.run_coroutine_threadsafe`.

---

### 5. frontend/app.js — tratar o evento na UI

No `switch(type)` dentro de `handleEvent()`:

```js
case "nome_do_evento": {
  const valor = ev.campo ?? null;
  // atualizar estado ou UI
  break;
}
```

Se o evento atualiza o badge, use `updateBadge("status")`.
Se mostra mensagem persistente, use `_showReconnectStatus(msg)`.
Se é passageiro, use `showToast(msg, "info"|"warn"|"error")`.

---

## Checklist antes de fechar

- [ ] `daemon.py` emite `_broadcast_sync` com o nome do evento
- [ ] `player.py` tem o parâmetro `on_nome` no `__init__` e o trata em `_handle_event`
- [ ] `main.py` define `_on_nome()` e passa para `Player(..., on_nome=_on_nome)`
- [ ] `playlist.py` tem `on_nome()` (síncrono) que delega via `run_coroutine_threadsafe` se precisar de async
- [ ] `app.js` tem o `case "nome_do_evento":` no `handleEvent`
- [ ] O nome do evento é **idêntico** em todas as camadas (string exata)

## Referência — eventos existentes

| Evento | Origem | O que faz |
|--------|--------|-----------|
| `file-loaded` | MPV callback | Marca que a live começou a reproduzir (`_live_has_played = True`) |
| `end-file` | MPV callback | Dispara avanço ou reconexão de live |
| `stream_reconnecting` | playlist.py | Informa tentativa de reconexão com causa e delay |
| `stream_reconnect_failed` | playlist.py | Esgotou tentativas — mostra toast de erro |
| `now_playing` | playlist.py | Atualiza UI com item em reprodução |
| `stopped` / `playlist_end` | playlist.py | Limpa UI, reseta badges |
| `position` | daemon via player | Sincroniza barra de progresso |
| `audio_level` | daemon | Atualiza VU meter |