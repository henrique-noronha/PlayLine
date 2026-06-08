# PlayLine — Documentação Técnica

Sistema de automação de playout televisivo para emissoras de pequeno porte (TVs Câmara, canais educativos, comunitários). TCC — Universidade Federal do Tocantins, 2026.

---

## Arquitetura

```
┌──────────────────┐   WebSocket /ws   ┌──────────────────────┐
│  Interface       │ ◄───────────────► │  FastAPI + Python     │
│  HTML/CSS/JS     │  eventos JSON      │  main.py + api/       │
│  (navegador)     │                   └──────────┬────────────┘
└──────────────────┘                              │ TCP :6600
                                                  ▼
                                       ┌──────────────────────┐
                                       │  MPV Daemon          │
                                       │  mpv_daemon.py       │
                                       │  (processo separado) │
                                       └──────────────────────┘
```

**Princípio central:** o daemon MPV é um processo independente — uma falha ou restart do servidor/interface não interrompe o sinal ao ar.

---

## Estrutura de Pastas

```
PlayLine/
├── PLAYLINE.md                     ← este arquivo
├── backend/
│   ├── main.py                     # FastAPI, lifecycle, ConnectionManager
│   ├── mpv_daemon.py               # Daemon MPV (TCP :6600, processo isolado)
│   ├── schedule.json               # Roteiro em execução (editável em runtime)
│   ├── checkpoint.json             # Posição salva para retomada após crash
│   ├── libmpv-2.dll                # Binária MPV (Windows)
│   ├── logos/                      # PNGs/JPGs dos logos de overlay
│   ├── core/
│   │   ├── events.py               # Constantes de eventos WebSocket
│   │   ├── player.py               # Cliente TCP do daemon (API de alto nível)
│   │   └── playlist.py             # Playlist Engine (orquestração)
│   └── api/
│       ├── routes.py               # Rotas HTTP REST
│       └── websocket.py            # Endpoint /ws + handlers de comando
└── frontend/
    ├── index.html                  # Página única (SPA)
    ├── app.js                      # Estado global, eventos WS, bootstrap
    ├── core/
    │   └── ws.js                   # WebSocket client (auto-reconexão 3s)
    ├── components/
    │   ├── logs.js                 # Log de eventos + badge de conexão
    │   ├── player.js               # Player HTML5 + sync com MPV
    │   ├── playlist.js             # Roteiro: render, D&D, miniaturas, seleção
    │   └── library.js              # Biblioteca: carregar pasta, D&D, seleção
    └── styles/
        ├── base.css                # Reset + variáveis CSS globais
        ├── layout.css              # Grid principal, header, card base
        ├── player.css              # Vídeo, progresso, controles, logos
        ├── schedule.css            # Itens do roteiro, D&D, seleção
        ├── library.css             # Itens da biblioteca, seleção
        └── log.css                 # Painel de log colapsável
```

---

## Backend — Módulos

### `main.py`
- Inicia FastAPI na porta **8000** (127.0.0.1)
- `lifespan`: cria `Player` e `PlaylistEngine`, carrega schedule, chama `restore_after_crash()`
- Monta frontend como estático em `/static`
- `ConnectionManager`: broadcast de eventos JSON para todos os clientes WS conectados

### `mpv_daemon.py` (TCP :6600)
Processo separado, sobrevive ao crash do servidor.

**Comandos aceitos (JSON por linha):**

| Comando | Descrição |
|---|---|
| `play` + `path` | Carrega e toca arquivo |
| `preload` + `path` | Enfileira próximo (sem flash) |
| `pause` / `resume` | Toggle pausa |
| `stop` | Para e limpa |
| `seek` + `seconds` + `mode` | Busca |
| `get_state` | Retorna estado atual |
| `set_logo` + `slot`/`filename`/`corner`/`active` | Configura overlay de logo |
| `list_logos` | Lista arquivos na pasta logos/ |

**Eventos broadcast (TCP):**

| Evento | Descrição |
|---|---|
| `end-file` + `reason` | Arquivo terminou (eof / error / stop) |
| `position` + `pos` | Posição atual (a cada 0.5s) |
| `logo_list` + `files` | Lista de logos disponíveis |
| `mpv_closed` | MPV foi fechado pelo usuário |
| `state_response` | Resposta ao get_state |

### `core/player.py`
Cliente TCP do daemon. Inicia o daemon automaticamente se não estiver rodando (subprocess DETACHED no Windows). Callbacks: `on_end_file`, `on_position`, `on_logo_list`.

### `core/playlist.py` — Playlist Engine
Orquestra a fila de reprodução.

- `_running`, `_paused`, `_index`: estado interno
- `_advance_seq`: evita duplo avanço (race condition)
- `_skip_end_file`: ignora end-files esperados (ao fazer stop/next manual)
- `_preloading`: True quando próximo já está pré-carregado no MPV

**Avanço automático:** `end-file` com reason `eof` ou `error` → `_advance()` → toca próximo → broadcast `now_playing`.

### `api/routes.py` — Rotas HTTP

| Rota | Método | Descrição |
|---|---|---|
| `/api/schedule` | GET | Retorna lista de itens |
| `/api/schedule` | PUT | Atualiza ordem/itens (JSON array) |
| `/api/state` | GET | Estado atual (running, index, item) |
| `/media?path=` | GET | Serve vídeo/áudio (valida extensão) |
| `/api/library?folder=` | GET | Lista vídeos em pasta (recursivo) |
| `/api/logos` | GET | Lista logos disponíveis |
| `/api/logos/{filename}` | GET | Serve logo para preview |
| `/api/thumbnail?path=` | GET | Gera miniatura 112×63 via ffmpeg |

### `api/websocket.py` — Comandos WS

| Ação | Descrição |
|---|---|
| `play` | Inicia reprodução |
| `pause` | Toggle pause/resume |
| `stop` | Para |
| `next` | Próximo item |
| `jump` + `index` | Pula para índice N |
| `set_logo` | Configura logo (slot, filename, corner, active) |
| `state` | Força broadcast do estado para todos |
| `reload_schedule` | Recarrega schedule.json do disco |

---

## Frontend — Componentes JS

### `app.js` — Estado Global

```javascript
state = {
  ws, connected,
  schedule: [],       // itens do roteiro
  currentIndex: -1,   // índice do clipe em reprodução
  playing: false,
  paused: false,
  currentItemStartTime: null,  // timestamp ms (para cálculo de horários)
  pausedAt: null,
  totalPausedMs: 0,
}
```

**Eventos WS recebidos e ações:**

| Evento | Ação |
|---|---|
| `now_playing` | Atualiza título, badge, carrega vídeo, timer |
| `paused` / `resumed` | Alterna badge e botões |
| `stopped` / `playlist_end` | Limpa interface |
| `position` | Sincroniza HTML5 video com MPV |
| `schedule_updated` | Re-renderiza roteiro |
| `logo_list` | Atualiza dropdowns de logo |

### `components/playlist.js` — Roteiro

**Estado local:**
- `thumbCache`: cache de miniaturas em memória + localStorage (`playline_thumb:<path>`)
- `durLoading`: Set de paths com carregamento de duração em andamento
- `dragSrcIdx`: índice sendo arrastado (interno)
- `libDragFile`: arquivo da biblioteca sendo arrastado
- `selectedScheduleIds`: Set de IDs selecionados (Ctrl+click)

**Funções principais:**
- `renderSchedule()` — reconstrói toda a lista DOM
- `generateThumb(path, imgEl)` — gera miniatura via canvas (seeking em vídeo oculto)
- `ensureDuration(path)` — carrega duração se não disponível
- `calcStartTimes()` / `updateStartTimes()` — calcula horários de início
- `initDnD(list)` — wires drag & drop nos itens
- `addFromLibrary(file, atIndex)` — insere item da biblioteca no roteiro
- `syncOrderToServer()` — PUT /api/schedule com ordem atual
- `updateScheduleSelectionUI()` — cria/atualiza botão "✕ N" de remoção em lote

**Regras de negócio importantes:**
- Clipe em reprodução (`state.playing && i === state.currentIndex`): NÃO pode ser movido, deletado ou selecionado
- Ctrl+click: toggle de seleção (exceto clipe em reprodução)
- Duplo-click: jump para aquele item
- Clique fora dos itens: deseleciona todos

### `components/library.js` — Biblioteca

**Estado local:**
- `selectedLibPaths`: Set de paths selecionados
- `currentLibFiles`: array dos arquivos da última carga

**Barra de seleção** (`#lib-sel-bar`): aparece entre o header e a lista quando há seleção; botão "Adicionar ao roteiro" chama `addFromLibrary` para cada path selecionado.

### `components/player.js` — Player HTML5

- Sincroniza com MPV via `syncPosition(pos)`: só busca se diferença > 1.5s
- `_showUnavailable()` / `_hideUnavailable()`: fallback para formatos não suportados pelo browser
- Logos: `_restoreLogoOverlays()` restaura overlays ao carregar novo vídeo

---

## CSS — Design System

### Variáveis (`base.css`)

```css
--bg:       #0f1117   /* fundo geral */
--surface:  #1a1d27   /* cards */
--surface2: #22263a   /* itens dentro de cards */
--accent:   #4f8ef7   /* azul principal */
--accent2:  #7c3aed   /* roxo */
--success:  #22c55e   /* verde */
--warning:  #f59e0b   /* laranja */
--danger:   #ef4444   /* vermelho */
--text:     #e2e8f0
--muted:    #64748b
--border:   #2d3148
--radius:   10px
--font:     'Segoe UI', system-ui, sans-serif
```

### Layout (`layout.css`)

- `main`: grid `420px 1fr` (coluna esquerda fixa, direita flexível)
- `.card`: padding 20px, border-radius 10px, background surface
- `.schedule-wrapper`: `position: relative; flex: 1` — ancora o card de roteiro
- `.schedule-card`: `position: absolute` preenchendo o wrapper — permite rolagem interna independente

### Itens do Roteiro (`schedule.css`)

Grid por item: `18px 22px 64px 1fr 68px 28px`
- 18px: drag handle (⠿ / ▶)
- 22px: índice
- 64px: miniatura (64×36px)
- 1fr: meta (título; caminho oculto com `display:none`)
- 68px: horário (início + data + duração)
- 28px: botão deletar

**Estados visuais:**
- `.active`: borda azul `--accent`, fundo `#1a2040`
- `.locked`: borda verde `--success` + animação pulse
- `.selected`: borda laranja `--warning`, fundo suave
- `.dragging`: opacidade 0.35
- `.drag-over`: borda azul tracejada

---

## Fluxo Típico: Reprodução

```
1. Operador clica Play
   → send({action:"play"})

2. WebSocket → playlist.py → player.play(path)
   → TCP: {"action":"play","path":"..."}

3. MPV Daemon carrega arquivo
   → broadcast TCP: position a cada 0.5s
   → quando termina: end-file {reason:"eof"}

4. player.py on_end_file → playlist._advance()
   → toca próximo → broadcast WS: now_playing

5. Frontend recebe now_playing
   → loadVideo, highlightActive, updateStartTimes
```

---

## Recuperação de Falhas

| Falha | Comportamento |
|---|---|
| Arquivo inválido | `end-file reason=error` → pula automaticamente |
| Interface fecha | Daemon continua tocando; ao reconectar restaura estado |
| Servidor reinicia | `restore_after_crash()` detecta daemon ativo, retoma posição |
| Daemon crash | Servidor reinicia daemon no próximo comando |

**Checkpoint:** posição salva a cada 5s em `checkpoint.json`. Ao restaurar, faz seek se posição > 2s.

---

## Logos (Overlay MPV)

- **2 slots independentes** (slot 1 e slot 2)
- Cantos: `tl`, `tr`, `bl`, `br` (padrões: br e bl)
- Arquivos em `backend/logos/` (PNG/JPG)
- Aplicados via `overlay-add` no MPV (BGRA pré-multiplicado)
- UI: seletor visual 4 zonas + toggle + dropdown de arquivo
- Estado salvo no localStorage (`playline_logo1_corner`, etc.)

---

## Dados — schedule.json

```json
[
  {
    "id": "item-<timestamp>",
    "title": "Nome do clipe",
    "path": "C:\\caminho\\absoluto\\video.mp4",
    "duration": 227
  }
]
```

- `id`: gerado pelo frontend com `Date.now()`
- `duration`: em segundos (inteiro); 0 = ainda não carregado
- Atualizado via PUT /api/schedule a cada mudança de ordem/inclusão/exclusão

---

## Convenções de Código

- **Backend:** Python async/await; eventos via callback thread-safe
- **Frontend:** ES6+ vanilla JS; sem frameworks; sem bundler (servido diretamente)
- **Comunicação:** JSON puro; sem biblioteca de serialização customizada
- **Thumbnails:** gerados no browser via canvas (seeking em vídeo oculto); fallback para `/api/thumbnail` (ffmpeg)
- **Persistência local:** `localStorage` para thumbnails (`playline_thumb:<path>`), pasta da biblioteca (`playline_library_folder`), logos (`playline_logo1_*`, `playline_logo2_*`)
