# Skill: add-api-route

## Quando usar
Sempre que precisar criar um novo endpoint HTTP no backend — GET, POST, PUT ou DELETE.
Use antes de escrever qualquer código quando a tarefa envolver "criar rota", "endpoint", "API" ou "buscar/salvar via HTTP".

## Onde ficam as rotas

Todas as rotas HTTP estão em `backend/api/routes.py` usando um `APIRouter`.
**Nunca criar rotas diretamente em `main.py`** — exceto `/login`, `/logout`, `/`, `/api/ping` e `/ws/preview` que são especiais do ciclo de vida da app.

```
backend/api/routes.py   ← aqui ficam todas as rotas de negócio
backend/api/websocket.py ← comandos em tempo real (não HTTP)
backend/main.py         ← apenas rotas de infraestrutura
```

---

## Passo a passo

### 1. Definir a rota em routes.py

```python
@router.get("/api/nome-do-recurso")
async def nome_da_funcao():
    if not _playlist_engine:
        raise HTTPException(status_code=503, detail="Engine não inicializada")
    resultado = alguma_operacao()
    return {"campo": resultado}
```

**Padrões obrigatórios:**
- Prefixo `/api/` em todas as rotas de negócio
- Verificar `if not _playlist_engine` antes de usar a engine
- Retornar dict (FastAPI serializa para JSON automaticamente)
- Usar `HTTPException` para erros — nunca retornar erro em campo de dados

**POST com body:**
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

class NomeRequest(BaseModel):
    campo: str
    outro: int = 0

@router.post("/api/nome-do-recurso")
async def criar_recurso(body: NomeRequest):
    resultado = _playlist_engine.fazer_algo(body.campo, body.outro)
    return {"ok": True, "id": resultado}
```

**DELETE com parâmetro na URL:**
```python
@router.delete("/api/nome-do-recurso/{id}")
async def deletar_recurso(id: int):
    ok = algum_modulo.delete(id)
    if not ok:
        raise HTTPException(status_code=404, detail="Não encontrado")
    return {"ok": True}
```

---

### 2. Validação de caminhos de arquivo

Se a rota recebe um caminho de arquivo do usuário, **sempre usar `_validate_path`**:

```python
@router.get("/api/media-info")
async def media_info(path: str):
    p = _validate_path(path, _MEDIA_EXTS)
    # usa p (Path validado e seguro)
    return {"size": p.stat().st_size}
```

`_validate_path` rejeita caminhos relativos, traversal (`..`) e extensões não permitidas.
`_MEDIA_EXTS` já cobre os formatos de vídeo e áudio suportados.

---

### 3. Rotas que precisam fazer broadcast

Se a ação deve notificar o frontend em tempo real:

```python
@router.post("/api/alguma-acao")
async def alguma_acao():
    resultado = _playlist_engine.fazer_algo()
    await _manager.broadcast({"event": "nome_evento", "campo": resultado})
    return {"ok": True}
```

---

### 4. Frontend — chamar a rota

```js
// GET simples
const res = await fetch("/api/nome-do-recurso");
const data = await res.json();

// POST com body
const res = await fetch("/api/nome-do-recurso", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({ campo: valor }),
});
const data = await res.json();
if (!res.ok) { showToast(data.detail, "error"); return; }

// DELETE
await fetch(`/api/nome-do-recurso/${id}`, { method: "DELETE" });
```

---

## Checklist

- [ ] Rota definida em `routes.py` (não em `main.py`)
- [ ] Prefixo `/api/` no path
- [ ] Verifica `_playlist_engine` antes de usar
- [ ] Caminhos de arquivo passam por `_validate_path`
- [ ] Erros usam `HTTPException` com `status_code` adequado
- [ ] Frontend trata `res.ok` antes de usar os dados
- [ ] Se notifica frontend: usa `await _manager.broadcast(...)`

## Referência — rotas existentes

| Rota | Método | O que faz |
|------|--------|-----------|
| `/api/stop` | POST | Para reprodução |
| `/api/schedule` | GET/PUT | Lê e salva roteiro |
| `/api/history` | GET | Lista histórico de reprodução |
| `/api/saved-schedules` | GET/POST | Lista e salva roteiros salvos |
| `/api/saved-schedules/{id}` | DELETE | Remove roteiro salvo |
| `/api/logos` | GET | Lista logos disponíveis |
| `/api/thumbnail` | GET | Retorna thumbnail de vídeo |
| `/media` | GET | Serve arquivo de mídia com range support |