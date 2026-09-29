"""Monta a demonstração interativa do site (docs/demo/) a partir do frontend real.

Copia frontend/ para docs/demo/static/ e gera docs/demo/index.html com os
caminhos ajustados e o servidor simulado (docs/demo/mock/demo.js) carregado
antes de tudo. Nenhum arquivo do app é alterado: a demo usa o mesmo HTML, CSS
e JS que o operador vê.

Rodar sempre que o frontend mudar:

    python tools/demo/build_demo.py
"""

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend"
DEMO = ROOT / "docs" / "demo"
STATIC = DEMO / "static"

# setup/ é o assistente de primeira execução, que não existe na demo
COPY = ["app.js", "components", "core", "i18n", "styles"]

HEAD_INJECT = """  <meta name="description" content="Demonstração interativa do PlayLine: a interface real do software de playout, com vídeos de exemplo." />
  <script src="mock/catalog.js"></script>
  <script src="mock/demo.js"></script>
"""


def copy_frontend():
    # Copia por cima e depois apaga o que sobrou de uma versão anterior. Apagar a
    # pasta inteira falha no Windows quando o editor está observando o diretório.
    STATIC.mkdir(parents=True, exist_ok=True)
    expected = set()
    for name in COPY:
        src = SRC / name
        files = [p for p in src.rglob("*") if p.is_file()] if src.is_dir() else [src]
        for f in files:
            rel = f.relative_to(SRC)
            dst = STATIC / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            expected.add(rel)
    for f in sorted(STATIC.rglob("*"), reverse=True):
        rel = f.relative_to(STATIC)
        if f.is_file() and rel not in expected:
            f.unlink()
        elif f.is_dir() and not any(f.iterdir()):
            f.rmdir()


def build_index():
    html = (SRC / "index.html").read_text(encoding="utf-8")
    html = html.replace('"/static/', '"static/')
    html = html.replace('"/api/logos/', '"mock/logos/')

    # Scripts referenciados que não existem no frontend viram 404 no site: fora.
    def keep(m):
        path = m.group(1)
        return m.group(0) if (STATIC / path.removeprefix("static/")).exists() else ""
    html = re.sub(r'\s*<script src="(static/[^"]+)"></script>', keep, html)

    html = html.replace("</title>\n", "</title>\n" + HEAD_INJECT, 1)
    # Depois dos estilos do app, para os ajustes da demo prevalecerem
    html = html.replace("</head>", '  <link rel="stylesheet" href="mock/demo.css" />\n</head>', 1)
    if "mock/demo.js" not in html or "mock/demo.css" not in html:
        raise SystemExit("não achei </title> ou </head> no index.html do frontend para injetar a demo")
    (DEMO / "index.html").write_text(
        "<!-- Gerado por tools/demo/build_demo.py a partir de frontend/index.html. Não editar à mão. -->\n" + html,
        encoding="utf-8",
    )


def main():
    if not (DEMO / "mock" / "catalog.js").exists():
        raise SystemExit("faltam os vídeos da demo: rode antes tools/demo/make_demo_media.py")
    copy_frontend()
    build_index()
    print("ok:", DEMO / "index.html")


if __name__ == "__main__":
    main()
