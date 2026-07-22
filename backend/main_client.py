"""Cliente leve do PlayLine — abre a interface em uma janela sem rodar servidor local."""

import base64
import socket
import sys
from pathlib import Path


def _logo_tag() -> str:
    if getattr(sys, "frozen", False):
        logos_dir = Path(sys._MEIPASS) / "logos"
    else:
        logos_dir = Path(__file__).parent / "logos"

    for name in ("LogoPlayLineD.png", "FavPlayline.png"):
        lp = logos_dir / name
        if lp.exists():
            b64 = base64.b64encode(lp.read_bytes()).decode()
            return f'<img src="data:image/png;base64,{b64}" style="max-width:280px;max-height:140px;object-fit:contain" alt="PlayLine" />'
    return "<span style='font-size:26px;font-weight:700;color:#e5e7eb'>PlayLine</span>"


def _build_html() -> str:
    logo = _logo_tag()
    return f"""<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlayLine — Conectar</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#111827;display:flex;flex-direction:column;align-items:center;
  justify-content:center;height:100vh;gap:32px;
  font-family:'Segoe UI',system-ui,sans-serif;color:#e5e7eb}}
.logo-wrap{{display:flex;flex-direction:column;align-items:center;gap:12px}}
.subtitle{{font-size:12px;color:#6b7280;letter-spacing:.08em;text-transform:uppercase;font-weight:500}}
form{{display:flex;flex-direction:column;gap:12px;width:280px}}
.field{{display:flex;flex-direction:column;gap:5px}}
label{{font-size:11px;color:#4b5563;font-weight:600;letter-spacing:.06em;text-transform:uppercase}}
input{{background:#1a2332;border:1px solid #2d3748;border-radius:8px;color:#e5e7eb;
  font-size:14px;padding:10px 13px;outline:none;transition:border-color .15s;width:100%;
  font-family:'Segoe UI',system-ui,sans-serif}}
input:focus{{border-color:#4f8ef7;background:#1e2a40}}
button{{background:#4f8ef7;border:none;border-radius:8px;color:#fff;cursor:pointer;
  font-size:13px;font-weight:600;padding:11px;width:100%;margin-top:4px;
  transition:background .15s;letter-spacing:.02em}}
button:hover{{background:#3b7de8}}
button:disabled{{background:#374151;cursor:not-allowed}}
#msg{{font-size:12px;text-align:center;min-height:16px}}
</style></head><body>
<div class="logo-wrap">
  {logo}
  <span class="subtitle">Conectar ao Servidor</span>
</div>
<form id="frm">
  <div class="field"><label>IP do Servidor</label>
    <input type="text" id="ip" placeholder="192.168.1.100" autocomplete="off" autofocus /></div>
  <p id="msg"></p>
  <button type="submit" id="btn">Conectar</button>
</form>
<script>
const frm = document.getElementById('frm');
const ipEl = document.getElementById('ip');
const btn  = document.getElementById('btn');
const msg  = document.getElementById('msg');

window.addEventListener('pywebviewready', () => {{
    window.pywebview.api.get_saved_ip().then(ip => {{ if (ip) ipEl.value = ip; }});
}});

frm.addEventListener('submit', async e => {{
    e.preventDefault();
    const ip = ipEl.value.trim();
    if (!ip) return;
    btn.disabled = true;
    btn.textContent = 'Conectando…';
    msg.style.color = '#6b7280';
    msg.textContent = 'Verificando conexão…';
    try {{
        const ok = await window.pywebview.api.test_connection(ip);
        if (ok) {{
            await window.pywebview.api.save_ip(ip);
            msg.style.color = '#4ade80';
            msg.textContent = 'Conectado! Carregando…';
            window.location.href = 'http://' + ip + ':8000';
        }} else {{
            msg.style.color = '#ef4444';
            msg.textContent = 'Não foi possível conectar. Verifique o IP e tente novamente.';
            btn.disabled = false;
            btn.textContent = 'Conectar';
        }}
    }} catch (ex) {{
        msg.style.color = '#ef4444';
        msg.textContent = 'Erro ao tentar conectar.';
        btn.disabled = false;
        btn.textContent = 'Conectar';
    }}
}});
</script>
</body></html>"""


class _Api:
    def _ip_file(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent / ".playline_server"
        return Path(__file__).parent / ".playline_server"

    def test_connection(self, ip: str) -> bool:
        try:
            s = socket.create_connection((ip.strip(), 8000), timeout=3)
            s.close()
            return True
        except Exception:
            return False

    def get_saved_ip(self) -> str:
        try:
            return self._ip_file().read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def save_ip(self, ip: str) -> None:
        try:
            self._ip_file().write_text(ip.strip(), encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    import webview

    api = _Api()
    window = webview.create_window(
        "PlayLine",
        html=_build_html(),
        js_api=api,
        width=600,
        height=500,
        min_size=(400, 400),
    )
    webview.start()
