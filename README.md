# PlayLine

> Sistema de automação de *playout* televisivo de código aberto, desenvolvido como TCC do curso de Ciência da Computação da Universidade Federal do Tocantins (UFT).

**PlayLine** é um software de automação de exibição televisiva voltado para emissoras de pequeno porte que não dispõem de orçamento para soluções comerciais. O sistema é projetado para ser operado por não especialistas, com interface simples.

---

## Funcionalidades

- Reprodução automatizada de vídeos via roteiro (`schedule.json`)
- Controles de play, pause, stop e avanço manual
- Avanço automático ao fim de cada clipe, com recuperação silenciosa em caso de erro
- **MPV Daemon** — processo independente que mantém o vídeo no ar mesmo após reinício do servidor
- **Retomada pós-crash** — checkpoint persiste a posição de reprodução; ao reiniciar, o sistema retoma de onde parou
- **Overlay de logos** — dois slots de logo com posicionamento livre nos quatro cantos da tela
- **Detecção de monitor secundário** — MPV abre em tela cheia no segundo monitor automaticamente
- **Biblioteca de vídeos** — navegação por pasta para adicionar clipes ao roteiro via interface
- Painel de controle em tempo real com relógio, tempo restante e próximo clipe
- Log de eventos ao vivo com opção de limpeza

---

## Arquitetura

PlayLine adota uma **arquitetura cliente-servidor orientada a eventos (EDA)** com três processos completamente isolados — uma falha na interface não interrompe o sinal ao ar.

```
┌─────────────────┐        WebSocket         ┌──────────────────────┐
│   Interface     │  ◄──────────────────────► │   Playlist Engine    │
│   HTML/JS       │    eventos assíncronos     │   Python + FastAPI   │
│   (navegador)   │                            │                      │
└─────────────────┘                            └──────────┬───────────┘
                                                          │ TCP :6600
                                                          ▼
                                               ┌──────────────────────┐
                                               │   MPV Daemon         │
                                               │   Processo isolado   │
                                               │   python-mpv / MPV   │
                                               └──────────────────────┘
```

**Fluxo de um evento típico:**
1. Operador clica "Próximo" na interface
2. Frontend envia `{"event": "next"}` via WebSocket
3. Playlist Engine consulta o `schedule.json` e envia `{"action": "play", "path": "..."}` ao Daemon via TCP
4. MPV emite `end-file` ao terminar → Daemon notifica o Playlist Engine → próximo clipe carrega automaticamente
5. Interface recebe `{"event": "now_playing", ...}` e atualiza em tempo real

**Tolerância a falhas:** arquivo corrompido ou inexistente → MPV emite `end-file` com `reason=error` → Playlist Engine pula para o próximo item automaticamente, sem intervenção do operador.

---

## Stack tecnológico

| Camada | Tecnologia | Motivo |
|---|---|---|
| Motor de vídeo | MPV + python-mpv | Gratuito, open source, eventos nativos assíncronos |
| Backend | Python 3 + FastAPI | Async-first, WebSocket nativo via ASGI |
| Daemon | asyncio TCP server | Processo isolado; sobrevive ao crash do servidor |
| Comunicação servidor↔daemon | JSON over TCP (newline-delimited) | Leve, sem dependências externas |
| Comunicação servidor↔interface | WebSocket (RFC 6455) | Bidirecional, baixa latência, sem polling |
| Roteiro | JSON | Leve, legível, editável em tempo de execução |
| Interface | HTML + CSS + JS nativos | Sem dependências de build, servido pelo FastAPI |
| Plataforma | Windows / Linux | Desenvolvimento em Windows, portável para Linux |

---

## Estrutura do projeto

```
playline/
├── backend/
│   ├── main.py              # Ponto de entrada FastAPI + wiring dos módulos
│   ├── mpv_daemon.py        # Ponto de entrada do MPV Daemon
│   ├── schedule.json        # Roteiro de programação (editável em runtime)
│   ├── logos/               # Imagens de logo para overlay
│   ├── core/
│   │   ├── events.py        # Definição de eventos do sistema
│   │   ├── player.py        # Interface com o MPV Daemon
│   │   └── playlist.py      # Playlist Engine: fila e avanço automático
│   ├── api/
│   │   ├── routes.py        # Rotas HTTP REST
│   │   └── websocket.py     # Handler WebSocket
│   └── daemon/
│       ├── daemon.py        # MPVDaemon: servidor TCP + controle do MPV
│       ├── checkpoint.py    # Persistência de posição para retomada pós-crash
│       ├── monitor.py       # Detecção de monitor secundário
│       ├── overlay.py       # Renderização de logos via MPV OSD
│       └── protocol.py      # Parsing do protocolo TCP
└── frontend/
    ├── index.html           # Interface de operação
    ├── app.js               # Inicialização e wiring dos componentes
    ├── core/
    │   └── ws.js            # Cliente WebSocket
    ├── components/
    │   ├── player.js        # Componente de reprodução e controles
    │   ├── playlist.js      # Componente de roteiro
    │   ├── library.js       # Componente de biblioteca de vídeos
    │   └── logs.js          # Componente de log de eventos
    └── styles/
        ├── base.css
        ├── layout.css
        ├── player.css
        ├── schedule.css
        ├── library.css
        └── log.css
```

---

## Instalação

### Pré-requisitos

- Python 3.11+
- [MPV](https://mpv.io/installation/) — no Windows, o arquivo `libmpv-2.dll` deve estar na pasta `backend/` ou no PATH do sistema

### Passos

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/playline.git
cd playline

# Instale as dependências Python
pip install fastapi uvicorn python-mpv

# Inicie o MPV Daemon (processo independente)
cd backend
python mpv_daemon.py

# Em outro terminal, inicie o servidor
cd backend
python main.py
```

Acesse `http://localhost:8000` no navegador para abrir a interface de operação.

---

## Formato do roteiro (schedule.json)

```json
{
  "items": [
    {
      "id": 0,
      "file": "C:/videos/abertura.mp4",
      "title": "Abertura institucional",
      "duration": null
    },
    {
      "id": 1,
      "file": "C:/videos/noticiario.mp4",
      "title": "Noticiário local",
      "duration": null
    }
  ]
}
```

O roteiro pode ser editado em tempo de execução pela interface ou diretamente no arquivo.

---

## Contexto acadêmico

PlayLine é desenvolvido como Trabalho de Conclusão de Curso (TCC) do curso de **Ciência da Computação** da **Universidade Federal do Tocantins (UFT)**.

- **Autor:** Henrique Noronha Fernandes
- **Orientador:** Prof. Dr. Edeilson Milhomem
- **Instituição:** Universidade Federal do Tocantins — Campus Palmas
- **Ano:** 2026

A motivação central do projeto é a democratização da infraestrutura de *broadcasting* para emissoras comunitárias nas regiões Norte e Nordeste do Brasil, onde a televisão linear ainda é o principal meio de acesso à informação para parcela significativa da população.

---

## Licença

[MIT](LICENSE) — livre para usar, modificar e distribuir.

---

> *"O sinal precisa continuar no ar."*
