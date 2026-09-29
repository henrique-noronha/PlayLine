"""Gera os vídeos, miniaturas e logos da demonstração do site (docs/demo/mock/).

Os clipes são desenhados quadro a quadro com Pillow e codificados pelo ffmpeg,
então não há material de terceiros nem questão de direito autoral. Rodar só
quando quiser trocar o conteúdo da demo:

    python tools/demo/make_demo_media.py

Requer Pillow (já está no requirements.txt) e o ffmpeg em backend/ffmpeg.exe
(ou no PATH).
"""

import json
import math
import random
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "demo" / "mock"
W, H, FPS = 960, 540, 25
FONTS = Path("C:/Windows/Fonts")

# ── Utilidades ───────────────────────────────────────────────────────────────


@lru_cache(maxsize=None)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


BLACK = "seguibl.ttf"   # Segoe UI Black
BOLD = "segoeuib.ttf"
REG = "segoeui.ttf"
SEMI = "seguisb.ttf" if (FONTS / "seguisb.ttf").exists() else "segoeuib.ttf"
MONO = "consolab.ttf"


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, a, b):
    return clamp((t - a) / (b - a))


def ease(x):
    return 1 - (1 - x) ** 3


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def grad(c1, c2, direction="v", size=(W, H)):
    """Degradê linear entre duas cores (v = de cima para baixo, h = esquerda para direita, d = diagonal)."""
    w, h = size
    if direction == "d":
        side = int(math.hypot(w, h)) + 2
        mask = Image.linear_gradient("L").resize((side, side)).rotate(45, resample=Image.BICUBIC)
        mask = mask.crop(((side - w) // 2, (side - h) // 2, (side - w) // 2 + w, (side - h) // 2 + h))
    else:
        mask = Image.linear_gradient("L").resize((w, h) if direction == "v" else (h, w))
        if direction == "h":
            mask = mask.rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
    return Image.composite(Image.new("RGB", (w, h), rgb(c2)), Image.new("RGB", (w, h), rgb(c1)), mask)


def radial(inner, outer, center, radius, size=(W, H)):
    w, h = size
    mask = Image.new("L", (w, h), 255)
    blob = Image.radial_gradient("L").resize((radius * 2, radius * 2))
    mask.paste(blob, (int(center[0] - radius), int(center[1] - radius)))
    return Image.composite(Image.new("RGB", (w, h), rgb(outer)), Image.new("RGB", (w, h), rgb(inner)), mask)


def alpha_text(layer, xy, text, fnt, color, alpha=1.0, anchor="la"):
    if alpha <= 0:
        return
    d = ImageDraw.Draw(layer)
    d.text(xy, text, font=fnt, fill=rgb(color) + (int(255 * alpha),), anchor=anchor)


def play_icon(d, cx, cy, r, color="#22c55e", chevron="#ffffff"):
    pts = [(cx - r * 0.55, cy - r * 0.8), (cx + r * 0.85, cy), (cx - r * 0.55, cy + r * 0.8)]
    d.polygon(pts, fill=rgb(color))
    w = max(2, int(r * 0.16))
    d.line([(cx - r * 0.2, cy - r * 0.3), (cx + r * 0.2, cy), (cx - r * 0.2, cy + r * 0.3)],
           fill=rgb(chevron), width=w, joint="curve")


def compose(base, layer):
    out = base.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


STATION = "PLAYLINE TV"

# ── Cenas ────────────────────────────────────────────────────────────────────


class Scene:
    duration = 10.0

    def __init__(self):
        self.setup()

    def setup(self):
        pass

    def frame(self, t) -> Image.Image:
        raise NotImplementedError


class Abertura(Scene):
    duration = 8.0

    def setup(self):
        self.bg = radial("#1d4ed8", "#050816", (660, 250), 900)

    def frame(self, t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx, cy = 690, 270
        grow = ease(prog(t, 0.0, 1.6))
        for r, width, color, speed, a in ((175, 12, "#22c55e", 40, 255), (215, 6, "#4f8ef7", -28, 230), (250, 3, "#ffffff", 18, 110)):
            start = t * speed
            span = 280 * grow
            d.arc((cx - r, cy - r, cx + r, cy + r), start, start + span, fill=rgb(color) + (a,), width=width)
        s = ease(prog(t, 0.6, 1.5))
        if s > 0:
            play_icon(d, cx + 8, cy, 90 * s)
        slide = ease(prog(t, 1.0, 1.9))
        alpha_text(layer, (70 - 40 * (1 - slide), 205), "BOA TARDE", font(BLACK, 76), "#ffffff", slide)
        alpha_text(layer, (74, 300), "A programação começa agora", font(REG, 28), "#dbeafe", prog(t, 2.0, 2.7))
        alpha_text(layer, (74, 58), STATION, font(MONO, 18), "#93c5fd", prog(t, 0.3, 1.0))
        return compose(self.bg, layer)


class Intervalo(Scene):
    duration = 6.0
    COLORS = ("#22c55e", "#4f8ef7", "#f5b83d", "#ef4444", "#a855f7")

    def setup(self):
        self.bg = grad("#0b1020", "#111a33", "v")

    def frame(self, t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for i, c in enumerate(self.COLORS):
            p_in = ease(prog(t, 0.1 * i, 0.9 + 0.1 * i))
            p_out = ease(prog(t, 4.8 + 0.08 * i, 5.8))
            x = -500 + 1500 * p_in + 1500 * p_out
            y0 = 60 + i * 90
            d.polygon([(x, y0), (x + 420, y0), (x + 340, y0 + 70), (x - 80, y0 + 70)], fill=rgb(c) + (230,))
        a = prog(t, 1.1, 1.7) * (1 - prog(t, 5.0, 5.6))
        if a > 0:
            d.rounded_rectangle((250, 196, 710, 344), 18, fill=(7, 10, 20, int(225 * a)))
        alpha_text(layer, (480, 250), "INTERVALO", font(BLACK, 64), "#ffffff", a, "mm")
        alpha_text(layer, (480, 310), "Voltamos em instantes", font(REG, 24), "#cbd5e1", a, "mm")
        return compose(self.bg, layer)


class Jornal(Scene):
    def __init__(self, bloco, headlines, duration, anchor_x, ticker):
        self.bloco, self.headlines, self.duration = bloco, headlines, duration
        self.anchor_x, self.ticker = anchor_x, ticker
        super().__init__()

    def setup(self):
        bg = radial("#2b5a93", "#0a1426", (480, 120), 640).convert("RGBA")
        stripes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stripes)
        for x in range(0, W, 64):
            sd.rectangle((x, 0, x + 2, H), fill=(255, 255, 255, 12))
        bg.alpha_composite(stripes)
        desk = grad("#0e1f3d", "#050b18", "v", (W, 170)).convert("RGBA")
        bg.alpha_composite(desk, (0, H - 170))
        ImageDraw.Draw(bg).rectangle((0, H - 170, W, H - 167), fill=rgb("#4f8ef7") + (160,))
        if self.anchor_x < 400:
            # Telão à direita do apresentador quando ele não está centralizado
            d = ImageDraw.Draw(bg)
            d.rounded_rectangle((560, 90, 890, 280), 10, fill=rgb("#0b1830"), outline=rgb("#4f8ef7"), width=3)
            for i, v in enumerate((70, 110, 90, 140, 125)):
                d.rectangle((600 + i * 55, 250 - v, 630 + i * 55, 250), fill=rgb("#22c55e" if i == 3 else "#4f8ef7"))
            d.text((600, 108), "OBRAS 2026", font=font(MONO, 16), fill=rgb("#93c5fd"))
        self.bg = bg

    def frame(self, t):
        img = self.bg.copy()
        d = ImageDraw.Draw(img)
        ax = self.anchor_x
        bob = math.sin(t * 1.3) * 2
        d.rounded_rectangle((ax - 95, 250 + bob, ax + 95, 380), 60, fill=rgb("#34435e"))
        d.ellipse((ax - 42, 165 + bob, ax + 42, 249 + bob), fill=rgb("#3d4d6b"))
        d.rectangle((ax - 150, 372, ax + 150, 384), fill=rgb("#16284a"))

        # Letreiro: entra em 1,5 s, troca a manchete a cada terço do bloco
        slide = ease(prog(t, 1.2, 2.0))
        if slide > 0:
            per = self.duration / len(self.headlines)
            idx = min(len(self.headlines) - 1, int(t // per))
            local = t - idx * per
            wipe = 1.0 if idx == 0 else ease(prog(local, 0, 0.5))
            x0 = 40 - 520 * (1 - slide)
            d.rectangle((x0, 402, x0 + 250, 432), fill=rgb("#dc2626"))
            d.text((x0 + 14, 417), f"JORNAL DA CÂMARA · BLOCO {self.bloco}", font=font(BOLD, 15), fill="#ffffff", anchor="lm")
            bar_w = 700
            d.rectangle((x0, 432, x0 + bar_w * max(wipe, 0.02), 478), fill=rgb("#f8fafc"))
            if wipe > 0.6:
                d.text((x0 + 16, 455), self.headlines[idx], font=font(BOLD, 25), fill=rgb("#0f172a"), anchor="lm")

        # Faixa de notícias rolando no rodapé
        d.rectangle((0, H - 34, W, H), fill=rgb("#07101f"))
        tf = font(SEMI, 17)
        text = "   ·   ".join(self.ticker) + "   ·   "
        tw = d.textlength(text, font=tf)
        off = (t * 90) % tw
        x = 130 - off
        while x < W:
            d.text((x, H - 17), text, font=tf, fill=rgb("#cbd5e1"), anchor="lm")
            x += tw
        d.rectangle((0, H - 34, 118, H), fill=rgb("#4f8ef7"))
        d.text((59, H - 17), "AGORA", font=font(BOLD, 16), fill="#ffffff", anchor="mm")
        return img.convert("RGB")


class Vacinacao(Scene):
    duration = 15.0

    def setup(self):
        self.bg = grad("#064e3b", "#0f766e", "d")
        rnd = random.Random(7)
        self.bubbles = [(rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(18, 70), rnd.uniform(12, 30)) for _ in range(16)]

    def frame(self, t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for x, y, r, speed in self.bubbles:
            yy = (y - t * speed) % (H + 160) - 80
            d.ellipse((x - r, yy - r, x + r, yy + r), fill=(94, 234, 212, 38))
        up = ease(prog(t, 0.4, 1.2))
        alpha_text(layer, (70, 170 + 30 * (1 - up)), "Vacine-se.", font(BLACK, 96), "#ffffff", up)
        alpha_text(layer, (74, 292), "Proteja quem você ama.", font(SEMI, 30), "#ccfbf1", prog(t, 1.8, 2.5))
        box = ease(prog(t, 4.5, 5.3))
        if box > 0:
            d.rounded_rectangle((70, 360, 70 + 640 * box, 420), 12, fill=(255, 255, 255, 235))
            if box > 0.9:
                alpha_text(layer, (92, 390), "Postos abertos de segunda a sábado, das 8h às 17h", font(BOLD, 21), "#064e3b", 1, "lm")
        alpha_text(layer, (74, 470), "CAMPANHA DE VACINAÇÃO 2026", font(MONO, 17), "#99f6e4", prog(t, 10.5, 11.3))
        return compose(self.bg, layer)


class Transparencia(Scene):
    duration = 14.0
    BARS = (("Saúde", 38), ("Educação", 31), ("Obras", 15), ("Social", 10), ("Cultura", 6))

    def setup(self):
        self.bg = grad("#f8fafc", "#e2e8f0", "v")

    def frame(self, t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        alpha_text(layer, (60, 52), "Transparência pública", font(BLACK, 44), "#0f172a", prog(t, 0.3, 1.0))
        alpha_text(layer, (62, 112), "Como o orçamento de 2026 foi aplicado", font(REG, 22), "#475569", prog(t, 0.9, 1.5))
        base_y, max_h = 440, 250
        for i, (name, v) in enumerate(self.BARS):
            g = ease(prog(t, 2.0 + 0.35 * i, 3.6 + 0.35 * i))
            x = 90 + i * 165
            h = max_h * v / 38 * g
            if g > 0:
                d.rounded_rectangle((x, base_y - h, x + 90, base_y), 8, fill=rgb("#16a34a" if i == 0 else "#2563eb"))
                if g > 0.95:
                    d.text((x + 45, base_y - h - 22), f"{v}%", font=font(BOLD, 22), fill=rgb("#0f172a"), anchor="mm")
            alpha_text(layer, (x + 45, base_y + 24), name, font(SEMI, 19), "#334155", prog(t, 1.6, 2.2), "mm")
        d.line((70, base_y, 890, base_y), fill=rgb("#94a3b8") + (255,), width=2)
        foot = prog(t, 9.0, 9.7)
        if foot > 0:
            d.rounded_rectangle((60, 486, 520, 522), 8, fill=rgb("#0f172a") + (int(255 * foot),))
            alpha_text(layer, (78, 504), "Acesse o portal da transparência", font(BOLD, 18), "#ffffff", foot, "lm")
        return compose(self.bg, layer)


class Previsao(Scene):
    duration = 20.0
    HOJE = (("Palmas", 34, 23, 36, "sol"), ("Araguaína", 33, 22, 35, "sol"), ("Gurupi", 35, 24, 37, "sol"))
    AMANHA = (("Palmas", 32, 22, 34, "nuvem"), ("Araguaína", 31, 21, 33, "nuvem"), ("Gurupi", 34, 23, 36, "sol"))

    def setup(self):
        self.bg = grad("#0c4a6e", "#081a33", "v")

    def _icon(self, d, cx, cy, kind, t):
        if kind == "sol":
            for k in range(8):
                a = t * 0.8 + k * math.pi / 4
                d.line((cx + math.cos(a) * 22, cy + math.sin(a) * 22, cx + math.cos(a) * 32, cy + math.sin(a) * 32),
                       fill=rgb("#fbbf24"), width=4)
            d.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=rgb("#fbbf24"))
        else:
            d.ellipse((cx - 22, cy - 22, cx + 6, cy + 6), fill=rgb("#fbbf24"))
            d.ellipse((cx - 26, cy - 6, cx + 8, cy + 20), fill=rgb("#e2e8f0"))
            d.ellipse((cx - 8, cy - 14, cx + 30, cy + 20), fill=rgb("#f1f5f9"))

    def frame(self, t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        second = t >= 10.0
        data = self.AMANHA if second else self.HOJE
        t0 = 10.0 if second else 0.0
        out = 1 - prog(t, 9.4, 10.0) if not second else 1
        head = "AMANHÃ" if second else "HOJE"
        alpha_text(layer, (60, 60), f"PREVISÃO DO TEMPO · {head}", font(MONO, 22), "#bae6fd", prog(t, t0 + 0.1, t0 + 0.6) * out)
        alpha_text(layer, (60, 92), "Tocantins", font(BLACK, 40), "#ffffff", prog(t, t0 + 0.1, t0 + 0.7) * out)
        for i, (city, temp, mn, mx, kind) in enumerate(data):
            s = ease(prog(t, t0 + 0.4 + 0.25 * i, t0 + 1.2 + 0.25 * i)) * out
            if s <= 0:
                continue
            x = 60 + i * 290 + 40 * (1 - s)
            a = int(255 * s)
            d.rounded_rectangle((x, 170, x + 260, 400), 16, fill=(255, 255, 255, int(24 * s)), outline=(255, 255, 255, int(50 * s)), width=2)
            d.text((x + 22, 200), city, font=font(BOLD, 24), fill=(255, 255, 255, a), anchor="lm")
            d.text((x + 22, 300), f"{temp}°", font=font(BLACK, 76), fill=(255, 255, 255, a), anchor="lm")
            d.text((x + 22, 370), f"mín {mn}°  ·  máx {mx}°", font=font(REG, 18), fill=(224, 242, 254, a), anchor="lm")
            if s > 0.9:
                self._icon(d, x + 205, 290, kind, t)
        warn = ease(prog(t, 3.5, 4.2))
        if warn > 0:
            d.rounded_rectangle((60, 440, 60 + 560 * warn, 486), 10, fill=rgb("#f5b83d") + (240,))
            if warn > 0.9:
                d.text((80, 463), "Umidade do ar abaixo de 30%: beba água", font=font(BOLD, 20), fill=rgb("#422006"), anchor="lm")
        return compose(self.bg, layer)


class Chamada(Scene):
    def __init__(self, tag, title, sub, colors, duration, pulse=False, title_size=108):
        self.tag, self.title, self.sub, self.colors = tag, title, sub, colors
        self.duration, self.pulse, self.title_size = duration, pulse, title_size
        super().__init__()

    def setup(self):
        self.bg = grad(self.colors[0], self.colors[1], "d")

    def frame(self, t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        band = ease(prog(t, 0.0, 0.8))
        y = 300
        d.polygon([(-50, y + 40), (W * band + 60, y - 50), (W * band + 60, y + 30), (-50, y + 120)], fill=(255, 255, 255, 20))
        tg = prog(t, 0.5, 1.0)
        if tg > 0:
            tf = font(MONO, 18)
            tw = d.textlength(self.tag, font=tf)
            d.rectangle((70, 150, 70 + tw + 28, 184), fill=rgb("#fbbf24") + (int(255 * tg),))
            d.text((84, 167), self.tag, font=tf, fill=rgb(self.colors[0]) + (int(255 * tg),), anchor="lm")
        up = ease(prog(t, 0.7, 1.5))
        alpha_text(layer, (64 - 30 * (1 - up), 196), self.title, font(BLACK, self.title_size), "#ffffff", up)
        alpha_text(layer, (70, 350), self.sub, font(BOLD, 34), "#fde68a", prog(t, 1.6, 2.2))
        if self.pulse:
            p = 0.5 + 0.5 * math.sin(t * 5)
            r = 10 + 4 * p
            d.ellipse((840 - r, 70 - r, 840 + r, 70 + r), fill=(239, 68, 68, int(160 + 95 * p)))
            alpha_text(layer, (862, 70), "AO VIVO", font(BOLD, 18), "#ffffff", 1, "lm")
        alpha_text(layer, (70, 470), f"Só na {STATION}", font(MONO, 18), "#ffffff", prog(t, self.duration - 4, self.duration - 3.3))
        return compose(self.bg, layer)


# ── Catálogo ─────────────────────────────────────────────────────────────────

TICKER = ["Câmara aprova calendário de audiências públicas",
          "Inscrições para o programa jovem aprendiz vão até sexta",
          "Previsão: tempo seco e calor em todo o estado",
          "Sessão plenária desta terça começa às 9h"]

CLIPS = [
    ("vinheta-abertura", "Vinhetas", "Vinheta de abertura", Abertura),
    ("vinheta-intervalo", "Vinhetas", "Vinheta de intervalo", Intervalo),
    ("jornal-bloco-1", "Programas", "Jornal da Câmara - Bloco 1",
     lambda: Jornal(1, ["Orçamento de 2027 entra em votação",
                        "Câmara aprova reforma da praça central",
                        "Audiência pública discute transporte escolar"], 30.0, 480, TICKER)),
    ("jornal-bloco-2", "Programas", "Jornal da Câmara - Bloco 2",
     lambda: Jornal(2, ["Obras na avenida principal seguem até dezembro",
                        "Feira do produtor volta ao centro no sábado"], 24.0, 300, TICKER[::-1])),
    ("campanha-vacinacao", "Institucionais", "Campanha de vacinação", Vacinacao),
    ("transparencia-publica", "Institucionais", "Transparência pública", Transparencia),
    ("previsao-do-tempo", "Boletins", "Previsão do tempo", Previsao),
    ("chamada-cidadania", "Chamadas", "Chamada - Cidadania",
     lambda: Chamada("NOVA TEMPORADA", "Cidadania", "Sábado, às 19h", ("#3b0764", "#9d174d"), 12.0)),
    ("chamada-sessao", "Chamadas", "Chamada - Sessão plenária",
     lambda: Chamada("TRANSMISSÃO", "Sessão plenária", "Terça, às 9h", ("#1c0505", "#7f1d1d"), 10.0,
                     pulse=True, title_size=86)),
]


def ffmpeg_bin() -> str:
    local = ROOT / "backend" / "ffmpeg.exe"
    if local.exists():
        return str(local)
    found = shutil.which("ffmpeg")
    if not found:
        sys.exit("ffmpeg não encontrado (coloque em backend/ffmpeg.exe ou no PATH)")
    return found


def render_clip(slug, scene, ff):
    media = OUT / "media" / f"{slug}.mp4"
    proc = subprocess.Popen(
        [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "27",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(media)],
        stdin=subprocess.PIPE,
    )
    frames = int(scene.duration * FPS)
    thumb_at = min(frames - 1, int(FPS * min(4.0, scene.duration * 0.4)))
    for i in range(frames):
        img = scene.frame(i / FPS)
        if i == thumb_at:
            img.resize((224, 126), Image.LANCZOS).save(OUT / "thumbs" / f"{slug}.jpg", quality=86)
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit(f"ffmpeg falhou em {slug}")
    return media


# ── Logos (canvas 1920x1080 transparente, como o app espera) ────────────────

def make_logos():
    bug = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    d = ImageDraw.Draw(bug)
    d.rounded_rectangle((1560, 56, 1864, 146), 22, fill=(8, 12, 22, 150))
    play_icon(d, 1622, 101, 34)
    d.text((1672, 101), "PLAYLINE", font=font(BLACK, 36), fill=(255, 255, 255, 235), anchor="lm")
    d.text((1674, 132), "TV", font=font(MONO, 20), fill=(147, 197, 253, 235), anchor="lm")
    bug.save(OUT / "logos" / "PlayLine TV.png", optimize=True)

    livre = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    d = ImageDraw.Draw(livre)
    d.rounded_rectangle((70, 930, 170, 1030), 12, fill=rgb("#16a34a") + (255,))
    d.text((120, 978), "L", font=font(BLACK, 76), fill=(255, 255, 255, 255), anchor="mm")
    livre.save(OUT / "logos" / "Classificação livre.png", optimize=True)

    selo = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    d = ImageDraw.Draw(selo)
    d.rounded_rectangle((1640, 940, 1860, 1024), 14, fill=rgb("#dc2626") + (235,))
    d.ellipse((1664, 970, 1688, 994), fill=(255, 255, 255, 255))
    d.text((1702, 982), "AO VIVO", font=font(BLACK, 38), fill=(255, 255, 255, 255), anchor="lm")
    selo.save(OUT / "logos" / "Selo ao vivo.png", optimize=True)

    # Logo da própria interface (cabeçalho) e favicon
    shutil.copy(ROOT / "backend" / "logos" / "LogoPlayLineD.png", OUT / "logos" / "LogoPlayLineD.png")
    shutil.copy(ROOT / "backend" / "logos" / "FavPlayline.png", OUT / "logos" / "FavPlayline.png")


def main():
    for sub in ("media", "thumbs", "logos"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    ff = ffmpeg_bin()
    make_logos()
    catalog = []
    for slug, folder, name, factory in CLIPS:
        scene = factory()
        if not only or slug in only:
            print(f"  {slug} ({scene.duration:.0f}s)...", flush=True)
            render_clip(slug, scene, ff)
        catalog.append({"slug": slug, "folder": folder, "name": name, "duration": scene.duration})
    logos = sorted(p.name for p in (OUT / "logos").glob("*.png") if p.name not in ("LogoPlayLineD.png", "FavPlayline.png"))
    (OUT / "catalog.js").write_text(
        "/* Gerado por tools/demo/make_demo_media.py. Não editar à mão. */\n"
        f"window.PLAYLINE_DEMO_CATALOG = {json.dumps({'clips': catalog, 'logos': logos}, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )
    print("ok:", OUT)


if __name__ == "__main__":
    main()
