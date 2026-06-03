# PlayLine

> Sistema de automação de *playout* televisivo de código aberto, desenvolvido como TCC do curso de Ciência da Computação da Universidade Federal do Tocantins (UFT).

**PlayLine** é um software de automação de exibição televisiva focado em emissoras de pequeno porte — TVs Câmaras, canais educativos e emissoras comunitárias — que não dispõem de orçamento para soluções comerciais. O sistema é projetado para ser operado por não especialistas, com interface simples e tolerância automática a falhas.

---

## Status do projeto

> **Em desenvolvimento** — protótipo funcional em andamento 

| Componente | |
|---|---|
| Motor de vídeo (MPV) | 
| Backend FastAPI + WebSocket | 
| Controles play / pause / stop |
| Avanço automático (end-file) |
| Recuperação de erros |
| Interface HTML/JS |
| Empacotamento .exe (PyWebView) |
| Testes de usabilidade (SUS) |

---

## Arquitetura

PlayLine adota uma **arquitetura cliente-servidor orientada a eventos (EDA)**. Os três processos principais rodam de forma completamente isolada — uma falha na interface não interrompe o sinal ao ar.

```
┌─────────────────┐        WebSocket         ┌──────────────────────┐
│   Interface     │  ◄──────────────────────► │   Playlist Engine    │
│   HTML/JS       │    eventos assíncronos     │   Python + FastAPI   │
│   (navegador)   │                            │                      │
└─────────────────┘                            └──────────┬───────────┘
                                                          │ python-mpv
                                                          ▼
                                               ┌──────────────────────┐
                                               │   Motor de Vídeo     │
                                               │   MPV (background)   │
                                               └──────────────────────┘
```

**Fluxo de um evento típico:**
1. Operador clica "Próximo" na interface
2. Frontend envia `{"event": "next"}` via WebSocket
3. Playlist Engine consulta o `schedule.json` e carrega o próximo item no MPV
4. MPV emite `end-file` ao terminar — Playlist Engine avança automaticamente
5. Interface recebe `{"event": "now_playing", ...}` e atualiza em tempo real

**Tolerância a falhas:** arquivo corrompido ou inexistente → MPV emite `end-file` com `reason=error` → Playlist Engine pula para o próximo item automaticamente, sem intervenção do operador.

---

## Stack tecnológico

| Camada | Tecnologia | Motivo |
|---|---|---|
| Motor de vídeo | MPV + python-mpv | Gratuito, open source, eventos nativos assíncronos |
| Backend | Python 3 + FastAPI | Async-first, WebSocket nativo via ASGI |
| Comunicação | WebSocket (RFC 6455) | Bidirecional, baixa latência, sem polling |
| Roteiro | JSON | Leve, legível, editável em runtime |
| Interface | HTML + CSS + JS nativos | Sem dependências de build, servido pelo FastAPI |
| Plataforma | Windows / Linux | Desenvolvimento em Windows, portável para Linux |

---

## Estrutura do projeto

```
playline/
├── backend/
│   ├── main.py          # FastAPI + WebSocket + orquestração
│   ├── player.py        # Integração MPV via python-mpv
│   ├── playlist.py      # Playlist Engine: fila e roteiro
│   └── schedule.json    # Roteiro de programação (editável)
└── frontend/
    ├── index.html        # Interface de operação
    ├── style.css         # Estilos
    └── app.js            # Conexão WebSocket e controles
```

---

## Instalação

### Pré-requisitos

- Python 3.11+
- [MPV](https://mpv.io/installation/) instalado e acessível no PATH (Windows: `.dll` na pasta do projeto ou no PATH)

### Passos

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/playline.git
cd playline

# Instale as dependências Python
pip install fastapi uvicorn python-mpv

# Configure o roteiro com seus arquivos de vídeo
# Edite backend/schedule.json

# Inicie o servidor
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
