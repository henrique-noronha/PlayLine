# Skill: build

## Quando usar
Sempre que precisar gerar o executável de distribuição, atualizar o `build.bat`, ou adicionar novos arquivos ao pacote PyInstaller.
Use antes de qualquer tarefa que envolva "gerar build", "compilar", "distribuir" ou "adicionar arquivo ao executável".

## Como buildar

Executar na raiz do projeto (onde fica `build.bat`):
```bat
build.bat
```

O script **deve ser executado de dentro da pasta `backend/`** — ele faz `cd /d "%~dp0"` automaticamente.
Resultado: `backend/dist/PlayLine/` contém o executável completo pronto para distribuição.

---

## Sequência do build.bat

```
[1/3] PlayLine-daemon.exe   ← daemon MPV (onefile)
[2/3] PlayLine.exe          ← servidor principal (onedir)
[3/3] PlayLine-Client.exe   ← cliente remoto (onefile)
[4/4] Montagem final        ← copia daemon + logos para dentro de dist/PlayLine/
```

---

## Quando adicionar novos arquivos ao build

### Arquivos de dados (não-Python) que o executável precisa acessar

Adicionar `--add-data` no comando PyInstaller correspondente no `build.bat`:

```bat
:: Sintaxe: "origem;destino_dentro_do_pacote"
--add-data "pasta_local;nome_no_pacote"
--add-data "arquivo.json;."
```

**Exemplos já existentes:**
```bat
--add-data "../frontend;frontend"   ← pasta frontend inteira
--add-binary "libmpv-2.dll;."       ← DLL MPV
--add-binary "ffmpeg.exe;."         ← ffmpeg (se existir)
```

### Arquivos copiados na etapa de montagem [4/4]

Para arquivos que ficam **ao lado** do executável (não dentro do pacote):

```bat
:: No bloco [4/4] do build.bat:
if not exist "dist\PlayLine\nova_pasta" mkdir "dist\PlayLine\nova_pasta"
if exist "nova_pasta" ( xcopy /e /i /y "nova_pasta\*" "dist\PlayLine\nova_pasta\" >nul 2>&1 )
```

Logos já seguem esse padrão:
```bat
if not exist "dist\PlayLine\logos" mkdir "dist\PlayLine\logos"
if exist "logos" ( xcopy /e /i /y "logos\*" "dist\PlayLine\logos\" >nul 2>&1 )
```

---

## Caminhos em tempo de execução

O executável muda os caminhos base. Sempre usar este padrão nos módulos Python:

```python
# Caminho de dados (ao lado do .exe no build, pasta do script em dev)
if getattr(sys, 'frozen', False):
    _DATA_DIR = Path(sys.executable).parent
else:
    _DATA_DIR = Path(__file__).parent

# Arquivos empacotados dentro do bundle PyInstaller
if getattr(sys, 'frozen', False):
    _ASSETS_DIR = Path(sys._MEIPASS) / "nome_pasta"
else:
    _ASSETS_DIR = Path(__file__).parent / "nome_pasta"
```

- `sys._MEIPASS` → arquivos incluídos via `--add-data` (somente leitura)
- `sys.executable.parent` → dados mutáveis (banco, logs, configurações)

---

## Dependências externas

| Arquivo | De onde vem | Como incluir |
|---------|-------------|--------------|
| `libmpv-2.dll` | Pasta `backend/` | `--add-binary "libmpv-2.dll;."` |
| `ffmpeg.exe` | Pasta `backend/` (opcional) | `set FFMPEG_ARG` já gerencia isso |
| `FavPlayline.ico` | Gerado pelo build a partir de `logos/FavPlayline.png` | Gerado automaticamente pelo build.bat |

## Checklist ao adicionar feature que precisa de novos arquivos

- [ ] Se é arquivo **lido pelo código** (JSON, PNG, DLL): adicionar `--add-data` ou `--add-binary`
- [ ] Se é arquivo **gerado/modificado em runtime** (banco, log, config): colocar em `sys.executable.parent`, não em `sys._MEIPASS`
- [ ] Se é pasta inteira copiada ao lado do exe: adicionar bloco `xcopy` na etapa `[4/4]` do `build.bat`
- [ ] Testar o executável gerado — erros de path em runtime não aparecem em dev

## Estrutura do dist gerado

```
dist/PlayLine/
├── PlayLine.exe              ← abre a interface
├── PlayLine-daemon.exe       ← processo MPV (iniciado pelo servidor)
├── logos/                    ← logos do sistema
├── Biblioteca/               ← pasta de biblioteca (criada vazia)
├── playline.db               ← banco SQLite (criado na primeira execução)
├── playline.log              ← log da aplicação
├── sessions.json             ← sessões de autenticação
└── _internal/                ← dependências Python empacotadas
```