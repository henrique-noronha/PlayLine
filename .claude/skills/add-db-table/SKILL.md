# Skill: add-db-table

## Quando usar
Sempre que precisar persistir um novo tipo de dado no SQLite.
Use antes de escrever qualquer código quando a tarefa envolver "salvar", "histórico", "persistir" ou "banco de dados".

## Estrutura do banco

Arquivo: `backend/core/playline.db` (dev) ou `<pasta do exe>/playline.db` (build).
Conexão centralizada em `backend/core/db.py` via `get_conn()`.

```
backend/core/db.py              ← definição das tabelas (init_db)
backend/core/<modulo>.py        ← funções de acesso (padrão: um arquivo por domínio)
backend/api/routes.py           ← endpoints HTTP que expõem os dados
```

---

## Passo a passo

### 1. db.py — criar a tabela

Dentro de `init_db()`, no `executescript` existente, adicionar o `CREATE TABLE IF NOT EXISTS`:

```python
def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            -- tabelas existentes...

            CREATE TABLE IF NOT EXISTS nome_tabela (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                campo_text TEXT    NOT NULL,
                campo_real REAL    NOT NULL DEFAULT 0.0,
                campo_bool INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    NOT NULL
            );
        """)
```

**Tipos SQLite usados no projeto:**
- `TEXT` — strings, datas ISO-8601, JSON blob
- `REAL` — floats (posição, duração, timestamp)
- `INTEGER` — inteiros, booleanos (0/1), PKs
- `INTEGER PRIMARY KEY AUTOINCREMENT` — ID gerado automaticamente

**Dado complexo como blob JSON** (como `saved_schedules.items`):
```sql
items TEXT NOT NULL   -- guarda json.dumps(lista)
```

---

### 2. core/novo_modulo.py — funções de acesso

Criar `backend/core/nome_modulo.py` seguindo o padrão de `history.py` e `saved_schedules.py`:

```python
import json
import logging
from datetime import datetime
from .db import get_conn

logger = logging.getLogger(__name__)


def list_all() -> list[dict]:
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, campo_text, created_at FROM nome_tabela ORDER BY id DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("Erro ao listar nome_tabela: %s", exc)
        return []


def save(campo_text: str, campo_real: float) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO nome_tabela (campo_text, campo_real, created_at) VALUES (?,?,?)",
            (campo_text, campo_real, now),
        )
        return cur.lastrowid


def delete(id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM nome_tabela WHERE id=?", (id,))
        return cur.rowcount > 0


# Se precisar serializar/deserializar JSON blob:
def get_items(id: int) -> list[dict]:
    conn = get_conn()
    row = conn.execute("SELECT items FROM nome_tabela WHERE id=?", (id,)).fetchone()
    conn.close()
    if not row:
        return []
    return json.loads(row["items"])
```

**Regras do padrão:**
- `get_conn()` sem `with` → fechar com `conn.close()` após SELECT
- `with get_conn() as conn:` → para INSERT/UPDATE/DELETE (commit automático)
- `dict(r)` para converter `sqlite3.Row` em dict serializável
- Nunca retornar `None` — retornar lista vazia ou `False` em caso de erro

---

### 3. api/routes.py — expor via HTTP

Importar o módulo e criar os endpoints:

```python
from core import nome_modulo

@router.get("/api/nome-recurso")
async def listar_nome_recurso():
    return nome_modulo.list_all()

@router.post("/api/nome-recurso")
async def salvar_nome_recurso(body: NomeRequest):
    new_id = nome_modulo.save(body.campo_text, body.campo_real)
    return {"ok": True, "id": new_id}

@router.delete("/api/nome-recurso/{id}")
async def deletar_nome_recurso(id: int):
    ok = nome_modulo.delete(id)
    if not ok:
        raise HTTPException(status_code=404, detail="Não encontrado")
    return {"ok": True}
```

---

## Checklist

- [ ] `CREATE TABLE IF NOT EXISTS` adicionado em `db.py → init_db()`
- [ ] Novo arquivo `core/nome_modulo.py` com funções puras (sem FastAPI, sem WebSocket)
- [ ] `get_conn()` sem `with` fechado com `.close()` nos SELECTs
- [ ] `with get_conn() as conn:` nos INSERT/UPDATE/DELETE
- [ ] Rotas adicionadas em `routes.py` (não em `main.py`)
- [ ] Sem `conn.close()` dentro de bloco `with` (já fecha automaticamente)

## Referência — tabelas existentes

| Tabela | Módulo de acesso | O que guarda |
|--------|-----------------|--------------|
| `schedule` | `playlist.py` | Roteiro atual (ordem, id, path, live, trim) |
| `checkpoint` | `checkpoint.py` | Posição de retomada após crash (1 linha) |
| `history` | `history.py` | Log de tudo reproduzido |
| `saved_schedules` | `saved_schedules.py` | Roteiros salvos com itens em JSON blob |